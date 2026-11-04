# MiniProject — YouTube Knowledge

ระบบผู้ช่วยค้นคว้าและเรียนรู้จากวิดีโอ YouTube ด้วย RAG, LLM และ Agentic AI

> สถานะปัจจุบัน: หมวด 01–07 รันได้ครบและมีชุดทดสอบ รันในเครื่องด้วย Docker ตาม [LOCAL_STACK.md](07_testing_deployment/LOCAL_STACK.md)
> และ deploy บนเซิร์ฟเวอร์จริงแบบ HTTPS ตาม [deploy/README.md](deploy/README.md)
> ยังไม่ได้ประเมินคุณภาพคำตอบโดยคน ดู [MAIN_RELEASE.md](07_testing_deployment/MAIN_RELEASE.md)

## เป้าหมาย

เปลี่ยนบทถอดเสียงจากวิดีโอที่เข้าถึงได้ให้เป็นฐานความรู้ ผู้ใช้เลือกคลิป ถามคำถาม สรุปและเปรียบเทียบเนื้อหา พร้อมตรวจสอบแหล่งอ้างอิงและเวลาในวิดีโอได้ จากนั้นต่อยอดเป็นผู้ช่วยค้นคว้า แผนเรียน แบบทดสอบ และแฟลชการ์ด

## แบ่งงาน 01–07

| โฟลเดอร์ | หน้าที่ | GitHub |
|---|---|---|
| [01_web_app](01_web_app/) | หน้าวางลิงก์ คลังคลิป ตัวเล่น แชต และหน้าผลการเรียนรู้ | [marisa46054](https://github.com/marisa46054) |
| [02_api_backend](02_api_backend/) | API ฐานข้อมูล ประวัติ และคิวงาน | [Mekmai4234](https://github.com/Mekmai4234) |
| [03_video_ingestion](03_video_ingestion/) | ตรวจลิงก์ ดึงข้อมูลและบทถอดเสียงพร้อมเวลา | [marisa46054](https://github.com/marisa46054) |
| [04_rag_knowledge](04_rag_knowledge/) | แบ่งข้อความ ทำ Embeddings และค้นคืนความรู้ | [Mekmai4234](https://github.com/Mekmai4234) |
| [05_ai_answers_analysis](05_ai_answers_analysis/) | ตอบ สรุป เปรียบเทียบ และแนบหลักฐาน | [marisa46054](https://github.com/marisa46054) |
| [06_research_learning_agent](06_research_learning_agent/) | วางแผนและค้นคว้าหลายขั้นตอน สร้างสื่อช่วยเรียน | [Mekmai4234](https://github.com/Mekmai4234) |
| [07_testing_deployment](07_testing_deployment/) | ทดสอบ ประเมิน AI และเตรียมระบบขึ้นใช้งาน | [Mekmai4234](https://github.com/Mekmai4234) |

แต่ละโฟลเดอร์มีเอกสารภาษาอังกฤษ 3 ไฟล์:
- `env.txt` — เครื่องมือ สภาพแวดล้อม และค่าตั้งค่าที่วางแผนใช้
- `step.txt` — ลำดับการทำงานของระบบ ตั้งแต่รับข้อมูลจนส่งผลลัพธ์
- `process.txt` — ภาพรวม สถาปัตยกรรม เทคนิค เหตุผลการออกแบบ และจุดเชื่อมต่อ

## แนวทางเอกสารและโมเดล

เอกสาร env / step / process ใช้รูปแบบสภาพแวดล้อม, Workflow Steps และ Process & Techniques ตามลำดับ เนื้อหาเป็นข้อกำหนดออกแบบของ YouTube Knowledge และยังไม่ยืนยันว่า implementation เสร็จแล้ว

ส่วน 05 และ 06 ใช้ Gemini ผ่าน Google GenAI SDK (`google-genai`) โดยตั้งค่า `GEMINI_API_KEY` และ `LLM_MODEL`
คงชื่อรุ่นที่ผู้ใช้ระบุ `gemini-3.5-flash` เป็นตัวอย่างแบบ configurable พร้อมหมายเหตุการเปลี่ยนเส้นทางรุ่นตาม Google ใน [05/env.txt](05_ai_answers_analysis/env.txt)
ส่วน 04 ใช้ Gemini embeddings (`gemini-embedding-2`) แยกจากโมเดลสร้างคำตอบ การเปลี่ยนโมเดลสร้างคำตอบหรือรุ่นสำรอง (`LLM_FALLBACK_MODELS`) จึงไม่ใช่การเปลี่ยน vector index

## เริ่มต้นสำหรับสมาชิก

1. อ่าน [ขอบเขตโครงการ](docs/project_scope.md) และ [สถาปัตยกรรม](docs/architecture.md)
2. เลือกงานและระบุผู้รับผิดชอบใน [ตารางแบ่งงาน](docs/task_assignment.md)
3. อ่านเอกสารทั้งสามไฟล์ของหมวดที่รับผิดชอบ
4. ทำตาม [คู่มือทำงานร่วมกัน](CONTRIBUTING.md) เพื่อสร้าง branch และส่ง Pull Request
5. เมื่อต้องตั้งค่าจริง ให้คัดลอก `.env.example` เป็น `.env` และเติมเฉพาะเครื่องของตนเอง

การติดตั้งและรันหน้าเว็บดู [คู่มือส่วน 01](01_web_app/README.md) ซึ่งมี manifest, pnpm-lock.yaml และคำสั่งทดสอบแล้ว
การติดตั้งและรันหมวด 02 ดู [คู่มือ Backend](02_api_backend/README.md) และ [ข้อตกลง API](docs/backend_api_contract.md)
การรันระบบเต็มในเครื่อง, backup และการต่ออายุ policy ของ Gemini ทุก 7 วัน ดู [LOCAL_STACK.md](07_testing_deployment/LOCAL_STACK.md)
การ deploy/อัปเดตเซิร์ฟเวอร์จริง, proxy สำหรับคำบรรยาย และการเปิดหน้าตรวจแชตของแอดมิน ดู [deploy/README.md](deploy/README.md)
หมวด 02 มี manifest, uv.lock, migration, คำสั่งทดสอบ และ Docker Compose สำหรับ Backend แล้ว

## Branch

- `main`: รุ่นที่ตรวจสอบแล้ว สำหรับส่งงานหรือปล่อยใช้งาน
- `develop`: รวมงานพัฒนา อ่านคู่มือและเริ่ม feature branch จากที่นี่
- `feature/NN-description`: เพิ่มฟีเจอร์ เช่น `feature/03-video-transcript`
- `fix/NN-description`: แก้บั๊ก เช่น `fix/05-invalid-citation`
- `docs/description`: ปรับเอกสาร เช่น `docs/team-setup`

เริ่มต้น main และ develop ใช้เอกสารชุดเดียวกัน ต่อไปให้งานฟีเจอร์เข้า develop ก่อน และรวมเข้า main เมื่อผ่านการตรวจสอบ

## สิ่งที่ต้องรู้

- ระบบใช้บทถอดเสียงเป็นหลัก ไม่ได้เข้าใจเหตุการณ์ที่มีเฉพาะภาพ
- คลิปที่ไม่มีคำบรรยายจะต้องแสดงสถานะ การถอดเสียงใหม่เป็นส่วนเสริมที่ยังไม่ได้ทำ
- YouTube มักบล็อกการดึงคำบรรยายจาก IP ของคลาวด์/VPS (`youtube_access_blocked`) บนเซิร์ฟเวอร์ต้องตั้ง proxy ตาม [deploy/README.md](deploy/README.md)
- หน้าตรวจแชตของแอดมิน (ดูถูกใจ/ไม่ถูกใจ) ปิดไว้เป็นค่าเริ่มต้น ต้องเปิดด้วย `CHAT_REVIEW_ENABLED` และ `CHAT_REVIEW_ADMIN_IDS`
- เทคโนโลยีและค่าตั้งค่าในเอกสารเป็นข้อเสนอ ต้องตรวจความเข้ากันได้และล็อกเวอร์ชันเมื่อพัฒนา
- การสรุปทุกคลิปต้องประมวลผลให้ครอบคลุม ไม่ใช้ top-k แล้วอ้างว่าครบทั้งหมด
- ห้ามนำรหัสลับจริงมาใส่ `env.txt` หรือ commit `.env`
- การเชิญผู้ร่วมงานเป็นสิทธิ์ระดับ repository ATCS-CPE ดูรายละเอียดใน CONTRIBUTING
