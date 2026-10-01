// SST39SF040 WiFi programmer for ESP32-S3 (write-only, no readback).
// The ESP makes its own WiFi network, you upload a 512 KB card .bin on the web page, it keeps up to ~17 of them
// in flash and burns the one you pick. Use the board's UART USB port (the native USB pins 19/20 are wired to the SST).
//
// Wiring: see the pin tables below. SST CE# -> GND, OE# -> +5 V, VDD -> +5 V, 100 nF across VDD/VSS.
// Only power the SST from the ESP while the card is OUT of the U-110.
#include <WiFi.h>
#include <WebServer.h>
#include <FFat.h>
#include <Preferences.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <vector>
#include "splash.h"
#include <ESPmDNS.h>
#include "esp_rom_crc.h"
#include "soc/gpio_reg.h"
#include "soc/usb_serial_jtag_reg.h"

// ---- change these if you rewire ----------------------------------------------------------------------
static const char *AP_SSID = "SST-PROG";
static const char *AP_PASS = "u110cards";                 // 8+ chars
static const uint8_t ADDR_PIN[19] = {42, 41, 40, 39, 38, 0, 45, 48, 10, 9, 3, 46, 47, 11, 12, 21, 20, 13, 19};  // A0..A18
static const uint8_t DATA_PIN[8] = {2, 1, 7, 15, 16, 17, 18, 8};                                                  // DQ0..DQ7
static const uint8_t WE_PIN = 14;                                                                                  // WE#
// -------------------------------------------------------------------------------------------------------

static const uint32_t IMAGE_SIZE = 512 * 1024;
static const int OLED_SDA = 4, OLED_SCL = 5, BTN_PIN = 6;  // 0.96" SSD1306 I2C display and an optional next-card button (to GND)
static const int PROGRAM_TRIES = 2;                       // program every byte this many times (catches stray missed bits)
static const char *DIR_CARDS = "/cards";

WebServer server(80);
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);

// ---------------------------------------------------------------- bus
static inline void putPins(const uint8_t *pins, int n, uint32_t v) {
  uint32_t setLo = 0, clrLo = 0, setHi = 0, clrHi = 0;
  for (int i = 0; i < n; i++) {
    uint8_t p = pins[i];
    bool one = (v >> i) & 1;
    if (p < 32) { if (one) setLo |= 1UL << p; else clrLo |= 1UL << p; }
    else        { if (one) setHi |= 1UL << (p - 32); else clrHi |= 1UL << (p - 32); }
  }
  REG_WRITE(GPIO_OUT_W1TS_REG, setLo);  REG_WRITE(GPIO_OUT_W1TC_REG, clrLo);
  REG_WRITE(GPIO_OUT1_W1TS_REG, setHi); REG_WRITE(GPIO_OUT1_W1TC_REG, clrHi);
}

// one write cycle: address + data settle, WE# low >= 40 ns (we hold ~1 us), WE# high
static inline void busWrite(uint32_t addr, uint8_t data) {
  putPins(ADDR_PIN, 19, addr);
  putPins(DATA_PIN, 8, data);
  REG_WRITE(GPIO_OUT_W1TC_REG, 1UL << WE_PIN);
  delayMicroseconds(1);
  REG_WRITE(GPIO_OUT_W1TS_REG, 1UL << WE_PIN);
}

static void initBus() {
#if defined(USB_SERIAL_JTAG_CONF0_REG)
  CLEAR_PERI_REG_MASK(USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_USB_PAD_ENABLE);   // free GPIO19/20 from the USB PHY
#endif
  digitalWrite(WE_PIN, HIGH);                     // WE# high before it becomes an output
  pinMode(WE_PIN, OUTPUT);
  for (int i = 0; i < 19; i++) { digitalWrite(ADDR_PIN[i], LOW); pinMode(ADDR_PIN[i], OUTPUT); }
  for (int i = 0; i < 8; i++)  { digitalWrite(DATA_PIN[i], LOW); pinMode(DATA_PIN[i], OUTPUT); }
}

// SST39SF040 command sequences (datasheet table 4): addresses 5555H / 2AAAH
static void cmdUnlock() { busWrite(0x5555, 0xAA); busWrite(0x2AAA, 0x55); }
static void chipErase() {
  cmdUnlock(); busWrite(0x5555, 0x80);
  cmdUnlock(); busWrite(0x5555, 0x10);
  delay(150);                                     // TSCE max 100 ms
}
static void byteProgram(uint32_t addr, uint8_t d) {
  for (int t = 0; t < PROGRAM_TRIES; t++) {
    cmdUnlock(); busWrite(0x5555, 0xA0); busWrite(addr, d);
    delayMicroseconds(25);                        // TBP max 20 us
  }
}

// ---------------------------------------------------------------- radio off while burning (no RF noise / current spikes)
static void radioOff() { WiFi.disconnect(true, false); WiFi.softAPdisconnect(true); WiFi.mode(WIFI_OFF); }
static void radioOn() {
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASS);
  Preferences p; p.begin("wifi", true); String s = p.getString("ssid", ""), pw = p.getString("pass", ""); p.end();
  if (s.length()) WiFi.begin(s.c_str(), pw.c_str());
  MDNS.end(); if (MDNS.begin("sstprog")) MDNS.addService("http", "tcp", 80);
}

// ---------------------------------------------------------------- burn job (runs in its own task)
enum { J_IDLE, J_ERASING, J_WRITING, J_DONE, J_ERROR };
static volatile int jobState = J_IDLE;
static volatile uint32_t jobDone = 0;
static char jobName[64] = "";
static char jobMsg[80] = "";
static String lastCard;                 // card burned last (kept across power cycles)

static void burnTask(void *arg) {
  String path = String(DIR_CARDS) + "/" + jobName;
  File f = FFat.open(path, "r");
  if (!f || f.size() != IMAGE_SIZE) {
    snprintf(jobMsg, sizeof jobMsg, "%s is not a 512 KB image", jobName);
    jobState = J_ERROR; if (f) f.close(); vTaskDelete(NULL);
  }
  jobDone = 0; jobState = J_ERASING;
  vTaskDelay(pdMS_TO_TICKS(400));                 // let the HTTP reply out, then kill the radio
  radioOff();
  chipErase();
  jobState = J_WRITING;
  static uint8_t buf[512];
  uint32_t addr = 0;
  uint32_t t0 = millis();
  while (addr < IMAGE_SIZE) {
    int n = f.read(buf, sizeof buf);
    if (n <= 0) break;
    for (int i = 0; i < n; i++) if (buf[i] != 0xFF) byteProgram(addr + i, buf[i]);   // erased bytes are already FF
    addr += n; jobDone = addr;
    if ((addr & 0x1FFF) == 0) vTaskDelay(1);      // let the web server breathe
  }
  f.close();
  int st;
  if (addr == IMAGE_SIZE) { snprintf(jobMsg, sizeof jobMsg, "wrote %s in %lu s - verify in the T48", jobName, (unsigned long)((millis() - t0) / 1000)); st = J_DONE; }
  else { snprintf(jobMsg, sizeof jobMsg, "read error at %lu", (unsigned long)addr); st = J_ERROR; }
  radioOn();
  if (st == J_DONE) { Preferences pr; pr.begin("state", false); pr.putString("last", jobName); pr.end(); lastCard = jobName; }
  jobState = st;
  Serial.println(jobMsg);
  vTaskDelete(NULL);
}

// ---------------------------------------------------------------- web
static const char PAGE[] PROGMEM = R"HTML(<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>SST programmer</title><style>
body{font-family:system-ui,sans-serif;background:#12161a;color:#eef1f3;max-width:640px;margin:20px auto;padding:0 14px}
h1{color:#6ec8e8;font-size:1.4em}.card{background:#1d2228;border:1px solid #33393f;border-radius:8px;padding:12px;margin:10px 0}
button,input[type=submit]{background:#3a3f46;color:#eef1f3;border:1px solid #555;border-radius:5px;padding:7px 14px;font-size:1em}
button.go{background:#c8322a;border-color:#c8322a}.row{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:6px 0}
#bar,#bar2{height:14px;background:#0c0f0d;border-radius:7px;overflow:hidden}#fill,#fill2{height:100%;width:0;background:#94ec44}.tabs button{margin-right:6px}select{background:#3a3f46;color:#eef1f3;border:1px solid #555;border-radius:5px;padding:6px}
small{color:#8a96a0}</style></head><body>
<h1>SST39SF040 programmer</h1>
<div class=tabs><button onclick="tab(0)">Cards</button><button onclick="tab(1)">Display</button><button onclick="tab(2)">Screen</button></div>
<div id=t0>
<div class=card><b>Stored cards</b><div id=list>...</div></div>
<div class=card><b>Upload a card image</b> <small>(512 KB .bin, connector order)</small>
<form method=POST action=/upload enctype=multipart/form-data><div class=row><input type=file name=f accept=.bin required><input type=submit value=Upload></div></form></div>
<div class=card><b>Home WiFi</b> <small id=wf>...</small>
<form method=POST action=/wifi><div class=row><input name=ssid placeholder=network required><input name=pass type=password placeholder=password><input type=submit value=Join></div></form>
<small>Joins your router too, so a PC on the same network can open the page. The SST-PROG network stays on.</small></div>
<div class=card><b>Status</b><div id=st>idle</div><div id=bar><div id=fill></div></div></div>
</div>
<div id=t1 style="display:none">
<div class=card><b>Hex Wizard screen</b>
<div class=row><label><input type=checkbox id=gl onchange=ui()> Glitch band</label></div>
<div class=row><label><input type=checkbox id=ipk onchange=ui()> Show the IP on the creature screen</label></div>
<div class=row><span>Idle animation</span><select id=an onchange=ui()><option value=0>Look around</option><option value=1>Gasp</option><option value=2>Look at the rack</option><option value=3>Random</option><option value=4>Off (blink only)</option></select></div>
<div class=row><button onclick="play()">Play it now</button><small>Settings are saved on the device.</small></div></div>
<div class=card><b>Storage</b><div id=sto>...</div><div id=bar2><div id=fill2></div></div></div>
</div>
<div id=t2 style="display:none">
<div class=card><b>Live screen</b><div><canvas id=cv width=128 height=64 style="width:100%;max-width:512px;image-rendering:pixelated;background:#000;border-radius:6px"></canvas></div>
<div class=row><button onclick="btn('up')">Up</button><button onclick="btn('down')">Down</button><button onclick="btn('sel')">Select</button></div>
<small>Same as the three buttons: Up and Down browse the stored cards, Select switches between the creature and the status screen. The picture updates about 3 times a second and pauses while a burn runs.</small></div>
</div>
<small>Only burn with the card OUT of the U-110.</small>
<script>
async function j(u){return (await fetch(u)).json()}
async function refresh(){
  const l=await j('/list');let h='';
  for(const c of l.cards)h+=`<div class=row><span>${c.name} <small>${(c.size/1024)|0} KB</small>${c.info?'<br><small>'+c.info.replace(/</g,'&lt;')+'</small>':''}</span><span><button class=go onclick="burn('${c.name}')">Burn</button> <button onclick="del('${c.name}')">Delete</button></span></div>`;
  document.getElementById('list').innerHTML=h||'<small>none yet</small>';
  document.getElementById('st').textContent=l.free_kb+' KB free';
}
async function burn(n){if(!confirm('Erase the SST and burn '+n+'?'))return;const r=await j('/burn?f='+encodeURIComponent(n));if(r.error)alert(r.error);poll()}
async function del(n){if(!confirm('Delete '+n+'?'))return;await fetch('/del?f='+encodeURIComponent(n));refresh()}
async function poll(){
  let s;
  try{s=await j('/status')}catch(e){document.getElementById('st').textContent='WiFi is off while burning - back in a few seconds...';setTimeout(poll,1500);return}
  const names=['idle','erasing chip...','writing','DONE','ERROR'];
  document.getElementById('st').textContent=names[s.state]+(s.msg?' - '+s.msg:'');
  document.getElementById('fill').style.width=(s.state==1?3:100*s.done/s.total)+'%';
  if(s.state==1||s.state==2)setTimeout(poll,400);else refresh();
}
async function wifi(){
  const w=await j('/wifi');
  document.getElementById('wf').textContent=w.connected?('connected to '+w.ssid+': http://'+w.ip+'/ or http://sstprog.local/'):(w.ssid?('joining '+w.ssid+'...'):'not set');
  if(w.ssid&&!w.connected)setTimeout(wifi,2000);
}
let scr=0;
function tab(n){for(let i=0;i<3;i++)document.getElementById('t'+i).style.display=i==n?'':'none';if(n==1)loadUi();scr=n==2;if(scr)screen()}
async function screen(){
  if(!scr)return;
  try{
    const b=new Uint8Array(await (await fetch('/screen')).arrayBuffer());
    const c=document.getElementById('cv').getContext('2d'),im=c.createImageData(128,64);
    for(let y=0;y<64;y++)for(let x=0;x<128;x++){const on=(b[(y>>3)*128+x]>>(y&7))&1,o=(y*128+x)*4;im.data[o]=on?150:0;im.data[o+1]=on?236:0;im.data[o+2]=on?255:0;im.data[o+3]=255}
    c.putImageData(im,0,0);
  }catch(e){}
  setTimeout(screen,320);
}
async function btn(b){await fetch('/btn?b='+b);setTimeout(()=>{},0)}
async function loadUi(){
  const u=await j('/ui');
  document.getElementById('gl').checked=!!u.gl;document.getElementById('ipk').checked=!!u.ip;document.getElementById('an').value=u.an;
  document.getElementById('sto').textContent=(u.used/1024).toFixed(1)+' MB used of '+(u.total/1024).toFixed(1)+' MB ('+u.pct+'%), '+u.cards+' cards, '+(u.free/1024).toFixed(1)+' MB free';
  document.getElementById('fill2').style.width=u.pct+'%';
}
async function ui(){await j('/ui?gl='+(document.getElementById('gl').checked?1:0)+'&ip='+(document.getElementById('ipk').checked?1:0)+'&an='+document.getElementById('an').value)}
async function play(){const a=+document.getElementById('an').value;await j('/ui?play='+(a<3?a:Math.floor(Math.random()*3)))}
refresh();poll();wifi();
</script></body></html>)HTML";

static String infoPath(String bin) { if (bin.endsWith(".bin")) bin = bin.substring(0, bin.length() - 4); return String(DIR_CARDS) + "/" + bin + ".txt"; }
static String readInfo(const String &bin) {
  File f = FFat.open(infoPath(bin), "r"); if (!f) return "";
  String s; while (f.available() && s.length() < 1500) s += (char)f.read(); f.close(); return s;
}

static String cleanName(String n) {
  int s = max(n.lastIndexOf('/'), n.lastIndexOf('\\'));
  if (s >= 0) n = n.substring(s + 1);
  String o;
  for (char c : n) if (isalnum(c) || c == '.' || c == '-' || c == '_') o += c;
  if (o.length() > 40) o = o.substring(o.length() - 40);
  if (!o.endsWith(".bin")) o += ".bin";
  return o;
}

static File uploadFile;
static bool uploadOk = true;
static String uploadMsg;

static void handleUpload() {
  HTTPUpload &up = server.upload();
  if (up.status == UPLOAD_FILE_START) {
    uploadOk = true; uploadMsg = "";
    if (jobState == J_ERASING || jobState == J_WRITING) { uploadOk = false; uploadMsg = "burn in progress"; return; }
    if (FFat.freeBytes() < IMAGE_SIZE + 4096) { uploadOk = false; uploadMsg = "storage full - delete a card first"; return; }
    uploadFile = FFat.open(String(DIR_CARDS) + "/" + cleanName(up.filename), "w");
    if (!uploadFile) { uploadOk = false; uploadMsg = "cannot create file"; }
  } else if (up.status == UPLOAD_FILE_WRITE) {
    if (uploadOk && uploadFile) uploadFile.write(up.buf, up.currentSize);
  } else if (up.status == UPLOAD_FILE_END) {
    if (uploadFile) { size_t sz = uploadFile.size(); String p = String(uploadFile.path()); uploadFile.close();
      if (sz != IMAGE_SIZE) { FFat.remove(p); uploadOk = false; uploadMsg = "file must be exactly 512 KB (got " + String(sz) + ")"; } }
  }
}

static String jsonEscape(const String &s) { String o; for (char c : s) { if (c == '"' || c == '\\') o += '\\'; o += c; } return o; }

// ---------------------------------------------------------------- burn start (shared by the web page and USB)
static bool startBurn(String n, String &err) {
  if (jobState == J_ERASING || jobState == J_WRITING) { err = "busy"; return false; }
  n = cleanName(n);
  if (!FFat.exists(String(DIR_CARDS) + "/" + n)) { err = "no such file"; return false; }
  n.toCharArray(jobName, sizeof jobName); jobMsg[0] = 0; jobDone = 0; jobState = J_ERASING;
  xTaskCreatePinnedToCore(burnTask, "burn", 6144, NULL, 1, NULL, 1);
  return true;
}

// ---------------------------------------------------------------- USB serial protocol (921600 baud, line commands)
//   PING | LIST | DEL name | PUT name size crchex (then raw data in 4 KB blocks, each acked with 'K') | BURN name | STATUS
static void serialPut(const char *name, uint32_t size, uint32_t crcWant) {
  if (jobState == J_ERASING || jobState == J_WRITING) { Serial.println("ERR busy"); return; }
  if (size != IMAGE_SIZE) { Serial.println("ERR size"); return; }
  if (FFat.freeBytes() < IMAGE_SIZE + 4096) { Serial.println("ERR full"); return; }
  String path = String(DIR_CARDS) + "/" + cleanName(name);
  File f = FFat.open(path, "w");
  if (!f) { Serial.println("ERR create"); return; }
  Serial.println("OK");
  static uint8_t blk[4096];
  uint32_t crc = 0;
  Serial.setTimeout(3000);
  for (uint32_t pos = 0; pos < size; pos += sizeof blk) {
    size_t want = min((uint32_t)sizeof blk, size - pos);
    if (Serial.readBytes(blk, want) != want) { f.close(); FFat.remove(path); Serial.println("ERR timeout"); return; }
    f.write(blk, want);
    crc = esp_rom_crc32_le(crc, blk, want);
    Serial.write('K');
  }
  f.close();
  if (crc != crcWant) { FFat.remove(path); Serial.println("ERR crc"); return; }
  Serial.println("DONE");
}

// ---------------------------------------------------------------- display settings (saved in flash; web page Display tab or the serial UI command)
static bool uiGlitch = true, uiShowIp = true;
static uint8_t uiAnim = 3;               // 0 look around, 1 gasp, 2 look at the rack, 3 random, 4 off (blink only)
static int uiPlayNow = -1;               // 0..2: start that animation right away (web play button, serial UI play=N)
static int cardCount();
static void uiLoad() { Preferences p; p.begin("ui", true); uiGlitch = p.getBool("gl", true); uiShowIp = p.getBool("ip", true); uiAnim = p.getUChar("an", 3); p.end(); if (uiAnim > 4) uiAnim = 3; }
static void uiSave() { Preferences p; p.begin("ui", false); p.putBool("gl", uiGlitch); p.putBool("ip", uiShowIp); p.putUChar("an", uiAnim); p.end(); }
static void flashStats(unsigned &totalK, unsigned &usedK, int &pct) {
  unsigned long t = FFat.totalBytes(), u = FFat.usedBytes();
  totalK = t / 1024; usedK = u / 1024; pct = t ? (int)((u * 100UL + t / 2) / t) : 0;
}
static String uiJson() {
  unsigned tk, uk; int pct; flashStats(tk, uk, pct);
  return String("{\"gl\":") + String(uiGlitch ? 1 : 0) + ",\"ip\":" + String(uiShowIp ? 1 : 0) + ",\"an\":" + String((int)uiAnim) +
         ",\"total\":" + String(tk) + ",\"used\":" + String(uk) + ",\"pct\":" + String(pct) + ",\"cards\":" + String(cardCount()) + ",\"free\":" + String(tk - uk) + "}";
}
static void uiApply(const String &gl, const String &ip, const String &an, const String &play) {
  bool ch = false;
  if (gl.length()) { uiGlitch = gl == "1"; ch = true; }
  if (ip.length()) { uiShowIp = ip == "1"; ch = true; }
  if (an.length()) { int a = an.toInt(); if (a >= 0 && a <= 4) { uiAnim = a; ch = true; } }
  if (ch) uiSave();
  if (play.length()) { int a = play.toInt(); if (a >= 0 && a <= 2) uiPlayNow = a; }
}

static void handleCmd(String l) {
  l.trim();
  if (l == "PING") Serial.println("PONG SST-PROG");
  else if (l == "UI" || l.startsWith("UI ")) {      // UI gl=0|1 ip=0|1 an=0..4 play=0..2
    String gl, ip, an, play; String rest = l.substring(2); int i = 0;
    while (i < (int)rest.length()) {
      int j = rest.indexOf(' ', i); if (j < 0) j = rest.length();
      String tok = rest.substring(i, j);
      if (tok.startsWith("gl=")) gl = tok.substring(3); else if (tok.startsWith("ip=")) ip = tok.substring(3);
      else if (tok.startsWith("an=")) an = tok.substring(3); else if (tok.startsWith("play=")) play = tok.substring(5);
      i = j + 1;
    }
    uiApply(gl, ip, an, play);
    Serial.println("UI " + uiJson());
  } else if (l == "LIST") {
    File d = FFat.open(DIR_CARDS);
    for (File e = d.openNextFile(); e; e = d.openNextFile()) if (!e.isDirectory()) Serial.printf("FILE %s %u\n", e.name(), (unsigned)e.size());
    Serial.println("END");
  } else if (l.startsWith("DEL ")) {
    String n = cleanName(l.substring(4));
    FFat.remove(String(DIR_CARDS) + "/" + n); FFat.remove(infoPath(n));
    Serial.println("OK");
  } else if (l.startsWith("TXT ")) {                 // TXT name len, then len raw bytes: card info (name + tone names) shown on the web page
    char nm[64]; unsigned len = 0;
    if (sscanf(l.c_str() + 4, "%63s %u", nm, &len) == 2 && len > 0 && len <= 2048) {
      static char buf[2049];
      Serial.println("OK"); Serial.setTimeout(3000);
      if (Serial.readBytes(buf, len) == len) { File f = FFat.open(infoPath(cleanName(nm)), "w"); if (f) { f.write((uint8_t *)buf, len); f.close(); } Serial.println("DONE"); }
      else Serial.println("ERR timeout");
    } else Serial.println("ERR args");
  } else if (l.startsWith("PUT ")) {
    char nm[64]; unsigned sz = 0, crc = 0;
    if (sscanf(l.c_str() + 4, "%63s %u %x", nm, &sz, &crc) == 3) serialPut(nm, sz, crc); else Serial.println("ERR args");
  } else if (l.startsWith("BURN ")) {
    String err;
    if (startBurn(l.substring(5), err)) Serial.println("OK started"); else Serial.println("ERR " + err);
  } else if (l.startsWith("PIN ")) {                 // pin test: PIN A5 / PIN D3 / PIN WE / PIN OFF (meter the SST pin)
    String n = l.substring(4); n.trim(); n.toUpperCase();
    putPins(ADDR_PIN, 19, 0); putPins(DATA_PIN, 8, 0); REG_WRITE(GPIO_OUT_W1TS_REG, 1UL << WE_PIN);   // idle: all low, WE# high
    int k = n.substring(1).toInt();
    if (n == "WE") REG_WRITE(GPIO_OUT_W1TC_REG, 1UL << WE_PIN);
    else if (n[0] == 'A' && k >= 0 && k < 19) putPins(ADDR_PIN, 19, 1UL << k);
    else if (n[0] == 'D' && k >= 0 && k < 8) putPins(DATA_PIN, 8, 1UL << k);
    Serial.println("OK " + n);
  } else if (l == "STATUS") {
    Serial.printf("STATUS %d %u %u %s\n", (int)jobState, (unsigned)jobDone, (unsigned)IMAGE_SIZE, jobMsg);
  }
}

static void serialPoll() {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleCmd(line); line = ""; }
    else if (c != '\r' && line.length() < 120) line += c;
  }
}

// ---------------------------------------------------------------- OLED (0.96" SSD1306, I2C on GPIO4/5) + next-card button on GPIO6
static bool oledOk = false;
static volatile uint8_t webBtn = 0;      // button press injected from the web page's Screen tab (an EV_ code)
static bool ladderMode = false;          // GPIO6 is a 3-button resistor ladder (true) or a single button (false)
static int viewIdx = -1;                // -1 = last burned card, 0.. = browsing the stored cards with the button
static uint32_t viewScrollAt = 0;
static int viewScroll = 0;

static String cardName(int i) {         // i-th stored .bin
  File d = FFat.open(DIR_CARDS); int k = 0;
  for (File e = d.openNextFile(); e; e = d.openNextFile()) {
    String nm = e.name();
    if (e.isDirectory() || !nm.endsWith(".bin")) continue;
    if (k++ == i) return nm;
  }
  return "";
}
static int cardCount() {
  File d = FFat.open(DIR_CARDS); int k = 0;
  for (File e = d.openNextFile(); e; e = d.openNextFile()) { String nm = e.name(); if (!e.isDirectory() && nm.endsWith(".bin")) k++; }
  return k;
}

static void wrapLines(const String &s, int cols, std::vector<String> &out) {
  String line;
  int i = 0, n = s.length();
  while (i < n) {
    int j = s.indexOf(' ', i); if (j < 0) j = n;
    String w = s.substring(i, j);
    while ((int)w.length() > cols) { if (line.length()) { out.push_back(line); line = ""; } out.push_back(w.substring(0, cols)); w = w.substring(cols); }
    if ((int)(line.length() + w.length() + (line.length() ? 1 : 0)) > cols) { out.push_back(line); line = w; }
    else line += (line.length() ? " " : "") + w;
    i = j + 1;
  }
  if (line.length()) out.push_back(line);
}

static void drawScreen() {
  if (!oledOk) return;
  oled.clearBuffer();
  oled.setFont(u8g2_font_5x8_tf);                                   // 25 columns x 8 rows
  bool busy = (jobState == J_ERASING || jobState == J_WRITING);
  if (busy) {
    oled.drawStr(0, 8, "BURNING");
    oled.drawStr(0, 19, String(jobName).substring(0, 25).c_str());
    oled.drawStr(0, 30, jobState == J_ERASING ? "erasing chip..." : "writing...");
    int pct = (int)((uint64_t)jobDone * 100 / IMAGE_SIZE);
    oled.drawFrame(0, 38, 128, 12);
    oled.drawBox(2, 40, (int)((uint64_t)jobDone * 124 / IMAGE_SIZE), 8);
    char b[24]; snprintf(b, sizeof b, "%d%%  radio off", pct);
    oled.drawStr(0, 62, b);
  } else {
    String ip = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : WiFi.softAPIP().toString();
    oled.drawStr(0, 8, ("SST PROG " + ip).c_str());
    oled.drawHLine(0, 10, 128);
    String name; String tag;
    int n = cardCount();
    if (viewIdx >= 0 && viewIdx < n) { name = cardName(viewIdx); tag = "stored " + String(viewIdx + 1) + "/" + String(n); }
    else { name = lastCard; tag = "last burned"; viewIdx = -1; }
    if (!name.length()) { oled.drawStr(0, 24, "no card burned yet"); oled.drawStr(0, 34, (String(n) + " stored").c_str()); }
    else {
      oled.drawStr(0, 20, name.substring(0, 25).c_str());
      oled.drawStr(0, 29, tag.c_str());
      std::vector<String> lines; wrapLines(readInfo(name), 25, lines);
      int visible = 3, total = (int)lines.size();
      if (total > visible && millis() - viewScrollAt > 2500) { viewScrollAt = millis(); viewScroll = (viewScroll + visible) % total; }
      if (total <= visible) viewScroll = 0;
      for (int r = 0; r < visible && viewScroll + r < total; r++) oled.drawStr(0, 40 + r * 9, lines[viewScroll + r].c_str());
    }
    const char *st = jobState == J_DONE ? "DONE" : jobState == J_ERROR ? "ERROR" : "ready";
    oled.drawHLine(0, 54, 128);
    oled.drawStr(0, 63, st);
    unsigned tk, uk; int pct; flashStats(tk, uk, pct);
    char sb[32]; snprintf(sb, sizeof sb, "%d cards %d%%/%.1fM", cardCount(), pct, tk / 1024.0);
    oled.drawStr(128 - strlen(sb) * 5, 63, sb);
  }
  oled.sendBuffer();
}

static void oledInit() {
  Wire.setPins(OLED_SDA, OLED_SCL);
  Wire.begin();
  Wire.setClock(1000000);                                  // 1 MHz: a full frame in ~10 ms, less tearing on camera
  for (uint8_t a : {0x3C, 0x3D}) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { oled.setI2CAddress(a << 1); oled.setBusClock(1000000); oled.begin(); oled.sendF("ca", 0xD5, 0xF0); oledOk = true; Serial.printf("OLED found at 0x%02X\n", a); break; }
  }
  if (!oledOk) Serial.println("no OLED found (SDA GPIO4, SCL GPIO5)");
  // detect a ladder: with the internal pull-DOWN on, a bare pin or an open single button reads ~0 V, the ladder reads ~2 V through its 6.8k
  pinMode(BTN_PIN, INPUT_PULLDOWN);
  delay(20);
  int mv0 = 0; for (int i = 0; i < 8; i++) mv0 += analogReadMilliVolts(BTN_PIN); mv0 /= 8;
  ladderMode = mv0 > 1000;
  Serial.printf("GPIO6 reads %d mV with the pull-down on\n", mv0);
  pinMode(BTN_PIN, ladderMode ? INPUT : INPUT_PULLUP);
  Serial.println(ladderMode ? "buttons: resistor ladder on GPIO6 (UP / DOWN / SELECT)" : "buttons: single button on GPIO6");
  uiLoad();
  Preferences p; p.begin("state", true); lastCard = p.getString("last", ""); p.end();
}

// ---------------------------------------------------------------- 3-button resistor ladder on one ADC pin (see README)
// 3V3 -[6.8k]- node -[18k]- GND, node -[100nF]- GND, node -[1.5k]-UP-GND, -[4.7k]-DOWN-GND, -[15k]-SELECT-GND  (all E12)
// idle 2.40 V, SELECT 1.80 V, DOWN 1.17 V, UP 0.56 V
enum { EV_NONE, EV_UP, EV_DOWN, EV_SELECT, EV_LEGACY };

static int ladderClass(int mv) {
  if (mv > 2090) return EV_NONE;       // idle
  if (mv > 1490) return EV_SELECT;
  if (mv > 890)  return EV_DOWN;
  if (mv >= 300) return EV_UP;
  return EV_NONE;                      // below 0.3 V: shorted or faulty, ignore
}

// returns one event per press; UP and DOWN repeat while held
static int readButtons() {
  if (webBtn) { int e = webBtn; webBtn = 0; return e; }
  static uint32_t lastSample = 0, downSince = 0, nextRep = 0;
  static int stable = EV_NONE, cand = EV_NONE, candCnt = 0;
  uint32_t now = millis();
  if (!ladderMode) {                                   // single button: short press = EV_LEGACY (next), hold 0.7 s = EV_SELECT
    static uint32_t downAt = 0; static bool held = false, longDone = false;
    bool dn = digitalRead(BTN_PIN) == LOW;
    if (dn && !held) { held = true; longDone = false; downAt = now; }
    else if (dn && held && !longDone && now - downAt > 700) { longDone = true; return EV_SELECT; }
    else if (!dn && held) { held = false; if (!longDone && now - downAt > 30) return EV_LEGACY; }
    return EV_NONE;
  }
  if (now - lastSample < 4) return EV_NONE;
  lastSample = now;
  int mv = 0;
  for (int i = 0; i < 4; i++) mv += analogReadMilliVolts(BTN_PIN);
  int c = ladderClass(mv / 4);
  if (c == cand) { if (candCnt < 255) candCnt++; } else { cand = c; candCnt = 1; }
  if (candCnt < 3 || c == stable) {                                  // needs 3 equal samples (about 12 ms) to change state
    if (stable == EV_UP || stable == EV_DOWN) {
      if (now >= nextRep && now - downSince > 500) { nextRep = now + 180; return stable; }
    }
    return EV_NONE;
  }
  stable = c;
  if (c == EV_NONE) return EV_NONE;
  downSince = now; nextRep = now + 500;
  return c;
}

// ---------------------------------------------------------------- creature: boot intro, then idle (blink + small glitch); button = status screen
enum { OV_SPLASH, OV_CREATURE, OV_STATUS, OV_MENU };
static uint8_t ovMode = OV_SPLASH;
static uint32_t ovStart = 0, ovAct = 0, ovTick = 0;
static int ovLastSeq = -1;
static uint8_t gbuf[1024];
static const uint32_t STATUS_TIMEOUT = 20000;          // status screen falls back to the creature after 20 s

static inline bool gGet(int x, int y) { return gbuf[y * 16 + (x >> 3)] & (1 << (x & 7)); }
static inline void gSet(int x, int y, bool v) { if (v) gbuf[y * 16 + (x >> 3)] |= (1 << (x & 7)); else gbuf[y * 16 + (x >> 3)] &= ~(1 << (x & 7)); }

static String ipCache; static uint32_t ipAt = 0;
static void showFrame(const uint8_t *frame, int glitchRow, int glitchShift, bool withIp) {
  memcpy_P(gbuf, frame, 1024);
  if (glitchRow >= 0) {
    for (int y = glitchRow; y < glitchRow + 4 && y < SPL_H; y++) {
      bool row[SPL_W];
      for (int x = 0; x < SPL_W; x++) row[x] = gGet((x - glitchShift + SPL_W) % SPL_W, y);
      for (int x = 0; x < SPL_W; x++) gSet(x, y, row[x]);
    }
  }
  oled.clearBuffer();
  oled.drawXBM(0, 0, SPL_W, SPL_H, gbuf);
  if (withIp && uiShowIp) {                                   // small IP at the bottom left, cutting into the picture a little
    if (ipCache.length() == 0 || millis() - ipAt > 3000) { ipAt = millis(); ipCache = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : WiFi.softAPIP().toString(); }
    oled.setFont(u8g2_font_4x6_tr);
    oled.setDrawColor(0); oled.drawBox(0, 57, ipCache.length() * 4 + 2, 7); oled.setDrawColor(1);
    oled.drawStr(0, 63, ipCache.c_str());
  }
  oled.sendBuffer();
}

// idle animations: (frame, ticks) steps from splash.h
static int8_t animSel = -1; static uint16_t animPos = 0; static uint8_t animTicks = 0; static uint32_t nextAnimAt = 0;
static const uint8_t *animSteps(int a, int &n) {
  switch (a) { case 0: n = SPL_ANIM0_N; return SPL_ANIM0; case 1: n = SPL_ANIM1_N; return SPL_ANIM1; default: n = SPL_ANIM2_N; return SPL_ANIM2; }
}

// ---------------------------------------------------------------- settings menu on the device (same settings as the web page's Display tab)
static uint8_t menuIdx = 0;
static const char *ANIM_NAMES[5] = {"Look around", "Gasp", "Rack", "Random", "Off"};
static void drawMenu() {
  if (!oledOk) return;
  oled.clearBuffer();
  oled.setFont(u8g2_font_5x8_tf);
  oled.drawStr(0, 8, "SETTINGS");
  oled.drawHLine(0, 10, 128);
  const char *lab[5] = {"Glitch band", "Show IP", "Animation", "Play it now", "Back"};
  for (int i = 0; i < 5; i++) {
    int y = 20 + i * 9;
    if (i == menuIdx) oled.drawStr(0, y, ">");
    oled.drawStr(8, y, lab[i]);
    const char *v = i == 0 ? (uiGlitch ? "on" : "off") : i == 1 ? (uiShowIp ? "on" : "off") : i == 2 ? ANIM_NAMES[uiAnim] : "";
    if (v[0]) oled.drawStr(128 - strlen(v) * 5, y, v);
  }
  oled.sendBuffer();
}
static void menuActivate() {
  switch (menuIdx) {
    case 0: uiGlitch = !uiGlitch; uiSave(); break;
    case 1: uiShowIp = !uiShowIp; uiSave(); break;
    case 2: uiAnim = (uiAnim + 1) % 5; uiSave(); break;
    case 3: uiPlayNow = (uiAnim < 3) ? uiAnim : (int)(esp_random() % 3); ovMode = OV_CREATURE; break;   // play it now: back to the creature to watch it
    default: ovMode = OV_CREATURE; break;
  }
}

static void oledLoop() {
  static uint32_t lastDraw = 0;
  static uint8_t lastJob = J_IDLE;
  uint32_t now = millis();
  if (!oledOk) return;
  if (ovStart == 0) { ovStart = now; ovAct = now; }
  bool busy = (jobState == J_ERASING || jobState == J_WRITING);

  if (jobState != lastJob) {                                      // a burn started, finished or failed: show the status screen
    lastJob = jobState;
    if (jobState != J_IDLE) { ovMode = OV_STATUS; ovAct = now; lastDraw = 0; }
  }
  int ev = readButtons();
  if (ev != EV_NONE) {
    ovAct = now; lastDraw = 0; viewScroll = 0; viewScrollAt = now;
    if (ovMode == OV_SPLASH) ovMode = OV_CREATURE;
    else if (ovMode == OV_CREATURE) { ovMode = OV_STATUS; viewIdx = -1; }
    else if (ovMode == OV_MENU) {
      if (ev == EV_UP) menuIdx = (menuIdx + 4) % 5;
      else if (ev == EV_DOWN || ev == EV_LEGACY) menuIdx = (menuIdx + 1) % 5;      // single button: a short press moves on
      else if (ev == EV_SELECT) menuActivate();
    }
    else if (ev == EV_SELECT) { ovMode = OV_MENU; menuIdx = 0; }                  // status screen -> settings
    else {
      int n = cardCount();
      if (ev == EV_UP) viewIdx = (viewIdx <= -1) ? n - 1 : viewIdx - 1;                  // -1 = the card burned last
      else if (viewIdx + 1 >= n) { viewIdx = -1; if (ev == EV_LEGACY) ovMode = OV_CREATURE; }
      else viewIdx++;
    }
  }
  if ((ovMode == OV_STATUS || ovMode == OV_MENU) && !busy && now - ovAct > STATUS_TIMEOUT) ovMode = OV_CREATURE;

  if (ovMode == OV_SPLASH) {
    int i = (now - ovStart) / SPL_FRAME_MS;
    if (i >= SPL_NSEQ) { ovMode = OV_CREATURE; return; }
    if (i != ovLastSeq) { ovLastSeq = i; showFrame(SPL_FRAMES[pgm_read_byte(&SPL_SEQ[i])], -1, 0, false); }
  } else if (ovMode == OV_CREATURE) {
    if (now - ovTick >= SPL_FRAME_MS) {
      ovTick = now;
      if (nextAnimAt == 0) nextAnimAt = now + 2500;
      uint32_t n = now / SPL_FRAME_MS;
      int f = SPL_IDLE;
      if (uiPlayNow >= 0 || (animSel < 0 && uiAnim != 4 && now >= nextAnimAt)) {
        animSel = (uiPlayNow >= 0) ? uiPlayNow : (uiAnim == 3 ? (int)(esp_random() % 3) : (int)uiAnim);
        uiPlayNow = -1; animPos = 0; animTicks = 0;
      }
      if (animSel >= 0) {                                       // an idle animation is playing
        int cnt; const uint8_t *st = animSteps(animSel, cnt);
        f = pgm_read_byte(&st[animPos * 2]);
        if (++animTicks >= pgm_read_byte(&st[animPos * 2 + 1])) {
          animTicks = 0;
          if (++animPos >= cnt) { animSel = -1; nextAnimAt = now + 3500 + esp_random() % 5500; }
        }
      } else {                                                  // plain idle: blink every ~3 s
        uint32_t ph = n % 45;
        if (ph == 38 || ph == 42) f = SPL_HALF; else if (ph >= 39 && ph <= 41) f = SPL_CLOSED;
      }
      bool gl = uiGlitch && ((n % 38) == 34 || (n % 38) == 35);
      showFrame(SPL_FRAMES[f], gl ? (int)(24 + (n * 7) % 30) : -1, (n & 1) ? 3 : -3, true);
    }
  } else if (ovMode == OV_MENU) {
    if (now - lastDraw > 200) { lastDraw = now; drawMenu(); }
  } else {
    if (now - lastDraw > (busy ? 1000 : 500)) { lastDraw = now; drawScreen(); }
  }
}

void setup() {
  Serial.setRxBufferSize(16384);
  Serial.begin(921600);
  delay(300);
  initBus();
  if (!FFat.begin(true)) Serial.println("FFat mount failed");
  FFat.mkdir(DIR_CARDS);
  oledInit();
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("\nSST programmer: join WiFi '%s' (pw %s), open http://%s/\n", AP_SSID, AP_PASS, WiFi.softAPIP().toString().c_str());
  { Preferences p; p.begin("wifi", true); String s = p.getString("ssid", ""), pw = p.getString("pass", ""); p.end();
    if (s.length()) { WiFi.begin(s.c_str(), pw.c_str()); Serial.println("joining saved network '" + s + "'"); } }
  if (MDNS.begin("sstprog")) MDNS.addService("http", "tcp", 80);
  server.on("/wifi", HTTP_GET, []() {
    Preferences p; p.begin("wifi", true); String s = p.getString("ssid", ""); p.end();
    bool ok = WiFi.status() == WL_CONNECTED;
    server.send(200, "application/json", "{\"ssid\":\"" + jsonEscape(s) + "\",\"connected\":" + (ok ? "true" : "false") +
                                             ",\"ip\":\"" + (ok ? WiFi.localIP().toString() : String("")) + "\"}");
  });
  server.on("/wifi", HTTP_POST, []() {
    String s = server.arg("ssid"), pw = server.arg("pass");
    if (s.length()) { Preferences p; p.begin("wifi", false); p.putString("ssid", s); p.putString("pass", pw); p.end();
      WiFi.disconnect(); WiFi.begin(s.c_str(), pw.c_str()); }
    server.sendHeader("Location", "/"); server.send(303);
  });

  server.on("/", HTTP_GET, []() { server.send_P(200, "text/html", PAGE); });
  server.on("/list", HTTP_GET, []() {
    String o = "{\"cards\":[";
    File d = FFat.open(DIR_CARDS); bool first = true;
    for (File e = d.openNextFile(); e; e = d.openNextFile()) {
      if (e.isDirectory()) continue;
      String nm = e.name(); if (!nm.endsWith(".bin")) continue;
      if (!first) o += ","; first = false;
      String info = readInfo(nm); info.replace("\r", ""); info.replace("\n", " | "); info.replace("\"", "'");
      o += "{\"name\":\"" + jsonEscape(nm) + "\",\"size\":" + String((unsigned)e.size()) + ",\"info\":\"" + jsonEscape(info) + "\"}";
    }
    o += "],\"free_kb\":" + String((unsigned)(FFat.freeBytes() / 1024)) + "}";
    server.send(200, "application/json", o);
  });
  server.on("/upload", HTTP_POST, []() {
    if (!uploadOk) server.send(400, "text/plain", "upload failed: " + uploadMsg);
    else { server.sendHeader("Location", "/"); server.send(303); }
  }, handleUpload);
  server.on("/del", HTTP_GET, []() {
    String n = cleanName(server.arg("f"));
    FFat.remove(String(DIR_CARDS) + "/" + n); FFat.remove(infoPath(n));
    server.send(200, "text/plain", "ok");
  });
  server.on("/burn", HTTP_GET, []() {
    String err;
    if (startBurn(server.arg("f"), err)) server.send(200, "application/json", "{\"ok\":1}");
    else server.send(200, "application/json", "{\"error\":\"" + err + "\"}");
  });
  server.on("/status", HTTP_GET, []() {
    server.send(200, "application/json", "{\"state\":" + String((int)jobState) + ",\"done\":" + String((unsigned)jobDone) +
                                             ",\"total\":" + String((unsigned)IMAGE_SIZE) + ",\"msg\":\"" + jsonEscape(jobMsg) + "\"}");
  });
  server.on("/ui", HTTP_GET, []() {
    uiApply(server.arg("gl"), server.arg("ip"), server.arg("an"), server.arg("play"));
    server.send(200, "application/json", uiJson());
  });
  server.on("/screen", HTTP_GET, []() {                      // the OLED buffer as 8 pages of 128 bytes, bit 0 = top pixel of the page
    server.sendHeader("Cache-Control", "no-store");
    server.send_P(200, "application/octet-stream", (const char *)oled.getBufferPtr(), 1024);
  });
  server.on("/btn", HTTP_GET, []() {
    String b = server.arg("b");
    webBtn = b == "up" ? EV_UP : b == "down" ? EV_DOWN : b == "sel" ? EV_SELECT : 0;
    server.send(200, "text/plain", "ok");
  });
  server.begin();
}

void loop() {
  static bool wasUp = false;
  bool up = WiFi.status() == WL_CONNECTED;
  if (up != wasUp) { wasUp = up; if (up) Serial.printf("home WiFi up: http://%s/ or http://sstprog.local/\n", WiFi.localIP().toString().c_str()); }
  serialPoll();
  oledLoop();
  server.handleClient();
  delay(1);
}
