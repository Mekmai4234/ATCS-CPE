# 01 · YouTube Knowledge Web

หน้าเว็บ React + TypeScript สำหรับนำเข้าคลิป เลือกแหล่งข้อมูล ถามพร้อม citation วิเคราะห์ และแสดงสื่อเรียนรู้ ใช้ Vite เพราะเป็นเว็บฝั่ง client ที่เชื่อม FastAPI อยู่แล้ว ไม่ต้องมี Node server อีกชุดตอนนำ build ไปใช้งาน

## เริ่มใช้งาน

ดูภาพตัวอย่าง: [หน้าคลังวิดีโอบนคอมพิวเตอร์](docs/screenshots/desktop.png) · [หน้าแชตบนมือถือ](docs/screenshots/mobile.png)

ใช้ Node.js 22.12+ หรือ 24 LTS และ pnpm 11.25.0 คำสั่งทั้งหมดด้านล่างรันจาก `MiniProject/01_web_app`:

```powershell
pnpm install --frozen-lockfile
pnpm dev
```

เปิด `http://127.0.0.1:3000` โหมดเริ่มต้นเชื่อม API จริงที่ `http://localhost:8000` หาก backend ยังไม่เปิดจะแสดงข้อผิดพลาด ไม่มีการเปลี่ยนไปใช้คำตอบจำลองอัตโนมัติ

Vite อ่านเฉพาะ `NEXT_PUBLIC_API_BASE_URL` จาก shared `.env` ที่ MiniProject และให้ค่าของ `01_web_app/.env` หรือ process environment มีลำดับเหนือกว่า โหลดค่าอื่นฝั่ง server เข้าหน้าเว็บไม่ได้ ต้องให้ backend ตั้ง `WEB_ORIGIN=http://127.0.0.1:3000` ตรงกับ origin ที่เปิดจริง หากเปิดผ่าน `localhost` ให้ตั้งค่า origin ให้ตรงกัน

ทดลองโดยไม่ใช้ backend:

```powershell
$env:VITE_DEMO_MODE = "true"
pnpm dev
```

โหมดนี้มีป้าย DEMO ตลอดเวลา ใช้บทเรียนและคำตอบสังเคราะห์ที่ไม่สัมพันธ์กับเนื้อหาคลิปจริง ไม่ดึง YouTube ไม่เรียก AI ไม่มีค่าใช้บริการภายนอก ปิด dev server แล้วใช้ `Remove-Item Env:VITE_DEMO_MODE` ก่อนกลับโหมด API จริง ค่านี้เป็น build-time configuration; เปลี่ยนแล้วต้องเริ่ม server/build ใหม่

## Flow ที่รองรับ

- นำเข้าหลาย URL แยกผล `accepted / existing / rejected` ตาม `input_index`; ไม่ปฏิเสธทั้งชุดเพราะลิงก์เดียวผิด
- คลังคลิปแบบแบ่งหน้า ช่องและช่วงวันที่จากรายการที่โหลด เลือกได้เฉพาะ `ready`; ไม่มี playlist filter
- แชตทั้ง `200` และ `202`; ส่ง scope ตามที่เลือกและเก็บ conversation ID สำหรับคำถามต่อเนื่อง
- Poll job แบบเรียงลำดับ หยุดเมื่อ `completed / partial / failed / cancelled`; `no_transcript` เป็น stage ของ import ที่อาจมี state `completed`
- สร้าง URL citation ใหม่จาก video ID และเวลา เปิด YouTube ตรงช่วง ไม่ใช้ URL ที่ model ส่งมาทันที
- Summary/compare, research พร้อม progress events, quiz, flashcards และ study plan; ดึง artifact ที่บันทึกไว้จาก ID
- แสดงผลบางส่วน ข้อมูลไม่ครอบคลุม หลักฐานไม่เพียงพอ และแหล่งข้อมูลเดิมใช้ไม่ได้อย่างชัดเจน
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
```

Browser tests ใช้ Google Chrome ที่ติดตั้งอยู่ และเปิด test servers บน `127.0.0.1:3001` กับ `:3002` โดยอัตโนมัติ จึงต้องให้สองพอร์ตนี้ว่าง หากต้องใช้ Chromium ของ Playwright ให้ติดตั้งด้วย `pnpm exec playwright install chromium` และเปลี่ยน `channel` ใน config ตามสภาพแวดล้อมของทีม

Browser suite ปกติทดสอบ demo และ mock HTTP contract โดยข้ามหนึ่งกรณี backend จริง ทดสอบ backend จริงแยกได้ด้วย Python 3.11+ ที่ติดตั้ง dependencies ของ module 02 แล้ว:

```powershell
python tests/backend_smoke.py --ref develop
```

สคริปต์อ่าน source module 02 จาก local Git ref ไปยังโฟลเดอร์ใหม่ใน `runtime/` เปิด API/worker บนพอร์ตว่าง ใช้ฐานข้อมูล fixture ใหม่ แล้วเรียก browser test โดยไม่ได้ mock HTTP ปิด API/worker เมื่อเสร็จ ไม่แก้ branch หรือฐานข้อมูลเดิม ต้องมี Node.js, Git, Chrome และ dependencies ของ module 02 อยู่บนเครื่อง

ผลทดสอบ HTML อยู่ใน `playwright-report/`; screenshots, backend logs และฐานข้อมูลทดสอบอยู่ใน `runtime/` ทั้งหมดถูก ignore ไม่ควร commit ดู [TEST_REPORT.md](TEST_REPORT.md) สำหรับผลที่รันจริง

## ข้อจำกัดปัจจุบัน

- ยังไม่ได้ตรวจ YouTube/embeddings/Gemini จริง การทดสอบกับ module 02 ใช้ fixture adapters จึงยืนยัน flow และ contract ไม่ยืนยันคุณภาพ AI
- ประวัติผลและงานที่กำลังติดตามอยู่ในหน่วยความจำของแท็บ รีโหลดแล้วไม่กู้ UI อัตโนมัติ งานที่ server รับไปแล้วอาจยังทำต่อ
- หยุดติดตามชั่วคราวเมื่อ GET ล้มเหลวต่อเนื่อง 3 ครั้ง หรือครบ 10 นาที พร้อมปุ่มติดตามอีกครั้ง; ไม่อ้างว่า server ล้มเหลวเพราะ browser timeout
- ไม่มีระบบสมาชิกหรือการแยกผู้ใช้ สอดคล้องกับ backend ต้นแบบผู้ใช้เดียว
- ใช้ external YouTube link สำหรับเล่นคลิปและ citation; มาสคอตเป็น PNG อ้างอิง ยังไม่มี animation
- ยังไม่ได้ deploy ขึ้นระบบใช้งานจริง

Build ที่ `dist/` ใช้กับ static hosting ได้ ค่าตั้งค่าฝั่ง browser ถูกฝังตอน build เก็บ API/model keys ไว้ที่ backend เท่านั้น

อ้างอิงเครื่องมือ: [Vite guide](https://vite.dev/guide/), [Playwright web server](https://playwright.dev/docs/test-webserver)
