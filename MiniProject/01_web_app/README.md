# 01 · YouTube Knowledge Web

## RAG Buddy mint UI / Floating Buddy — 24 October 2026

ปรับตามภาพชุดล่าสุด `D:\Web\New folder` เป็นพื้นมิ้นต์สว่าง มาสคอตแยกชั้นที่มองตาม pointer และแชต Buddy ลากย้ายได้หลัง login ใช้ state/API/conversation ร่วมกับหน้าแชตเต็ม ดู [รายงานรอบนี้](MINT_BUDDY_REPORT.md) และ [ที่มา assets/rig](design/buddy-rig/README.md) ส่วนรายงานฉากป่าเดิมเก็บไว้เป็นประวัติ

**ใช้ HttpSessionPort เดิม:** challenge nonce, Google exchange, session/CSRF และ Admin API มาจากงานทีม 02 ซึ่งรวมใน develop แล้ว ไม่สร้าง auth client ซ้ำ การทดสอบอัตโนมัติจำลอง external Google verifier; การใช้บัญชี Google จริงและการตั้งค่า HTTPS/origins ยังต้องตรวจแยกก่อนประกาศพร้อม deploy

หน้าเว็บ React + TypeScript สำหรับนำเข้าคลิป เลือกแหล่งข้อมูล ถามพร้อม citation วิเคราะห์ และแสดงสื่อเรียนรู้ ใช้ Vite เพราะเป็นเว็บฝั่ง client ที่เชื่อม FastAPI อยู่แล้ว ไม่ต้องมี Node server อีกชุดตอนนำ build ไปใช้งาน

## เริ่มใช้งาน

ดูภาพตัวอย่าง: [หน้าคลังวิดีโอบนคอมพิวเตอร์](docs/screenshots/desktop.png) · [หน้าแชตบนมือถือ](docs/screenshots/mobile.png)

ใช้ Node.js 22.12+ หรือ 24 LTS และ pnpm 11.25.0 คำสั่งทั้งหมดด้านล่างรันจาก `MiniProject/01_web_app`:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

เปิด `http://127.0.0.1:3000` เว็บจะตรวจ `/api/auth/me` และขอ challenge ก่อนแสดงปุ่ม GIS ไม่เปลี่ยนไปใช้ demo อัตโนมัติเมื่อ backend ไม่พร้อม โดยปริยาย Vite proxy `/api` ไป `NEXT_PUBLIC_API_BASE_URL` (เริ่มที่ `http://localhost:8000`) ส่วน production ต้องตั้ง reverse proxy `/api` เอง

Vite อ่านเฉพาะ `NEXT_PUBLIC_API_BASE_URL` จาก shared `.env` ที่ MiniProject และให้ค่าของ `01_web_app/.env` หรือ process environment มีลำดับเหนือกว่า โหลดค่าอื่นฝั่ง server เข้าหน้าเว็บไม่ได้ ต้องให้ backend ตั้ง `WEB_ORIGIN=http://127.0.0.1:3000` ตรงกับ origin ที่เปิดจริง หากเปิดผ่าน `localhost` ให้ตั้งค่า origin ให้ตรงกัน

ให้ทีม 02 ตั้ง `GOOGLE_CLIENT_ID` และ trusted origin ของเว็บ ค่า Client ID/nonce ที่ใช้กับ Google มาจาก challenge ของ server ค่า `VITE_API_SAME_ORIGIN=true` เป็นค่าเริ่มต้น; หากเลือก `false` ต้องตรวจ cookie/CORS ทุกสถานะ รวมถึง 401/403 ดูรายละเอียดในคู่มือ auth

ทดลองโดยไม่ใช้ backend:

```powershell
$env:VITE_DEMO_MODE = "true"
pnpm dev
```

เลือกบัญชี A, B หรือผู้ดูแลบนหน้า login โหมดนี้มีป้าย DEMO ตลอดเวลา ใช้ข้อมูลและคำตอบสังเคราะห์ ไม่ดึง YouTube ไม่เรียก AI ไม่มีค่าใช้บริการภายนอก เก็บเฉพาะตัวเลือกบัญชี fixture ใน sessionStorage; ไม่เก็บ credential จริง ปิด dev server แล้วใช้ `Remove-Item Env:VITE_DEMO_MODE` ก่อนกลับโหมดเริ่มต้น ค่านี้เป็น build-time configuration; เปลี่ยนแล้วต้องเริ่ม server/build ใหม่

## Flow ที่รองรับ

- นำเข้าหลาย URL แยกผล `accepted / existing / rejected` ตาม `input_index`; ไม่ปฏิเสธทั้งชุดเพราะลิงก์เดียวผิด
- คลังคลิปแบบแบ่งหน้า ช่องและช่วงวันที่จากรายการที่โหลด เลือกได้เฉพาะ `ready`; ไม่มี playlist filter
- แชตทั้ง `200` และ `202`; ส่ง scope ตามที่เลือกและเก็บ conversation ID สำหรับคำถามต่อเนื่อง
- Poll job แบบเรียงลำดับ หยุดเมื่อ `completed / partial / failed / cancelled`; `no_transcript` เป็น stage ของ import ที่อาจมี state `completed`
- สร้าง URL citation ใหม่จาก video ID และเวลา เปิด YouTube ตรงช่วง ไม่ใช้ URL ที่ model ส่งมาทันที
- Summary/compare, research พร้อม progress events, quiz, flashcards และ study plan; ดึง artifact ที่บันทึกไว้จาก ID
- แสดงผลบางส่วน ข้อมูลไม่ครอบคลุม หลักฐานไม่เพียงพอ และแหล่งข้อมูลเดิมใช้ไม่ได้อย่างชัดเจน
- เมื่อลบคลิป ปิดเฉพาะ citation ของคลิปนั้นในคำตอบและสื่อเรียนรู้ที่แสดงอยู่ เก็บ job ID และเวอร์ชันแหล่งข้อมูลเพื่อตรวจซ้ำเมื่อรีเฟรช การนำเข้า video ID เดิมไม่เปิดหลักฐานเก่ากลับมา
- การส่งคำขอเดิมซ้ำใช้ payload และ Idempotency-Key เดิม งานใหม่ใช้ key ใหม่; import ใช้การ deduplicate ของ backend
- ยกเลิกงานที่กำลังติดตาม ลบคลิปหลังยืนยัน และ retry งาน import/delete เฉพาะที่ backend อนุญาต
- รองรับมือถือ คีย์บอร์ด reduced motion และแสดงข้อความที่ไม่เชื่อถือผ่าน React text โดยไม่เปิด raw HTML

ใน DEMO ลองนำเข้า `https://youtu.be/NoCaption01` เพื่อดูกรณีไม่มีบทถอดเสียง พิมพ์คำถามที่มี `รอผล` เพื่อทดลอง chat 202 หรือ `ไม่มีข้อมูล` เพื่อดู insufficient evidence ส่วน research แสดงผลบางส่วนเป็นตัวอย่าง

## API contract ที่อ้างอิง

ตรวจจาก **local `develop@25427fe`**, `MiniProject/docs/backend_api_contract.md` และ Pydantic schemas ของ module 02 ด้วย `git show` การทดสอบแรกอ่าน source ผ่าน Git โดยไม่เปลี่ยน branch และภายหลัง sync develop ก่อนเปิด PR จึงมี backend source ใน checkout แล้ว ดู [API_CONTRACT.md](API_CONTRACT.md) สำหรับ mapping ที่ใช้กับ frontend

## ตรวจสอบ

```powershell
pnpm typecheck
pnpm format:check
pnpm test
pnpm test:browser
pnpm build
pnpm test:production
```

Browser tests ใช้ Google Chrome ที่ติดตั้งอยู่ และเปิด test servers บน `127.0.0.1:3001`, `:3002` และ `:3003` โดยอัตโนมัติ จึงต้องให้สามพอร์ตนี้ว่าง หากต้องใช้ Chromium ของ Playwright ให้ติดตั้งด้วย `pnpm exec playwright install chromium` และเปลี่ยน `channel` ใน config ตามสภาพแวดล้อมของทีม

พอร์ต 3001/3002 ใช้ standalone workspace harness เพื่อรักษา regression เดิม พอร์ต 3003 ใช้ SessionShell กับ test adapter `/__test__/` และ mock GIS โดยเฉพาะ ไม่ใช่ contract ทีม 02 และไม่ใช่การทดสอบ Google จริง โหมด harness ทั้งสองห้าม build สำหรับ deploy

Browser suite ปกติทดสอบ demo และ mock HTTP contract โดยข้าม 8 integration cases: auth 7 เคสรันด้วย identity_smoke ด้านล่าง ส่วน legacy single-user 1 เคสใช้ snapshot เก่าเท่านั้น ต้องมี Python 3.11+ และ dependencies ของ module 02:

```powershell
python tests/backend_smoke.py --ref 69f5347
```

ทดสอบ session/nonce/Admin/ownership ด้วย HTTP backend ที่เปิด auth และ verifier fixture (ต้องมี dependencies ของ module 02) ใช้พอร์ต 3001–3004:

```powershell
python tests/identity_smoke.py --checkout
```

ใช้ `python tests/identity_smoke.py --checkout` เพื่อตรวจหน้า entry ปกติกับ source backend ใน actual checkout และฐานข้อมูลแยก โดยไม่แก้ backend หรือฐานข้อมูลเดิม หรือใช้ `--ref origin/develop` เพื่อตรวจ snapshot จาก Git ไม่ใช่การทดสอบบัญชี Google จริง

## ใช้ Floating Buddy

- เปิดปุ่ม Buddy หลังเข้าสู่ระบบ เลือกคลิปที่พร้อม แล้วถามได้ด้วย Enter; Shift+Enter ขึ้นบรรทัดใหม่และไม่ส่งระหว่าง IME composition
- ลากปุ่มวงกลม หรือใช้เมนูจุดสามจุดเลือกมุม/คืนตำแหน่ง การลากไม่เปิดแชต และเก็บเฉพาะ `{v,x,y}` ใน localStorage; storage ใช้ไม่ได้ก็ยังใช้งานได้
- ย่อแล้วเปิดกลับหรือไปหน้าแชตเต็ม ใช้ข้อความ/คลิป/conversation ชุดเดียวกัน เปลี่ยน scope แล้วคำถามถัดไปเริ่ม conversation ใหม่พร้อมแจ้งให้ทราบ
- ประวัติใช้ GET ของ conversation ที่ session นี้รู้จัก มี pagination และไม่เก็บ ID/ประวัติใน localStorage ปัจจุบัน backend ไม่มี endpoint รายการ conversations ทั้งบัญชี จึงไม่สร้างเมนูรายการย้อนหลังที่เรียก API สมมติ
- Suggestion เติมร่างข้อความเท่านั้น ไม่ส่งหรือเรียก LLM จนกดยืนยัน หน้า Login ไม่เปิดแชตส่วนตัว หน้า Admin ใช้ console เดิม; กลับพื้นที่เรียนรู้เพื่อใช้ Buddy ด้วยคลังของบัญชีผู้ดูแลเอง
- มือถือใช้ modal sheet พร้อม focus/Escape; desktop เป็น non-modal เลื่อนอ่านของเก่าแล้วจะไม่ดึงกลับท้ายเมื่อมีคำตอบใหม่

สคริปต์อ่าน source module 02 จาก local Git ref ไปยังโฟลเดอร์ใหม่ใน `runtime/` เปิด API/worker บนพอร์ตว่าง ใช้ฐานข้อมูล fixture ใหม่ แล้วเรียก browser test โดยไม่ได้ mock HTTP ปิด API/worker เมื่อเสร็จ ไม่แก้ branch หรือฐานข้อมูลเดิม ต้องมี Node.js, Git, Chrome และ dependencies ของ module 02 อยู่บนเครื่อง

ผลทดสอบ HTML อยู่ใน `playwright-report/`; screenshots, backend logs และฐานข้อมูลทดสอบอยู่ใน `runtime/` ทั้งหมดถูก ignore ไม่ควร commit ดู [TEST_REPORT.md](TEST_REPORT.md) สำหรับผลที่รันจริง

## ข้อจำกัดปัจจุบัน

- ยังไม่ได้ตรวจ YouTube/embeddings/Gemini จริง การทดสอบกับ module 02 ใช้ fixture adapters จึงยืนยัน flow และ contract ไม่ยืนยันคุณภาพ AI
- ประวัติผลและงานที่กำลังติดตามอยู่ในหน่วยความจำของแท็บ รีโหลดแล้วไม่กู้ UI อัตโนมัติ งานที่ server รับไปแล้วอาจยังทำต่อ
- หยุดติดตามชั่วคราวเมื่อ GET ล้มเหลวต่อเนื่อง 3 ครั้ง หรือครบ 10 นาที พร้อมปุ่มติดตามอีกครั้ง; ไม่อ้างว่า server ล้มเหลวเพราะ browser timeout
- ระบบสมาชิกใช้ HttpSessionPort และ API auth/session ของ 02; ยังต้องตรวจ Google จริงตาม [AUTH_INTEGRATION.md](AUTH_INTEGRATION.md)
- ใช้ external YouTube link สำหรับเล่นคลิปและ citation; Buddy เคลื่อนไหวจากภาพหลายเลเยอร์และรองรับ reduced motion
- ยังไม่ได้ deploy ขึ้นระบบใช้งานจริง

งานภาพรอบ 24 ตุลาคม 2026 เพิ่มส่วนแสดงหลักฐานที่ใช้ร่วมกันและการพักติดตามงาน
429/503 โดยไม่ส่งคำถามซ้ำเอง ส่วน visual-only chat ยังไม่เปิดใน production:
develop ยังไม่มี API ภาพ และ branch สัญญา v2 ของ 02 ยังระบุว่า chat ใช้ transcript-v1
ดู [EVIDENCE_HANDOFF.md](EVIDENCE_HANDOFF.md) สำหรับข้อต่อที่ต้องตกลงและเกณฑ์ทดสอบร่วมกับ 07

Build ที่ `dist/` ใช้กับ static hosting ได้ ค่าตั้งค่าฝั่ง browser ถูกฝังตอน build เก็บ API/model keys ไว้ที่ backend เท่านั้น

อ้างอิงเครื่องมือ: [Vite guide](https://vite.dev/guide/), [Playwright web server](https://playwright.dev/docs/test-webserver)
