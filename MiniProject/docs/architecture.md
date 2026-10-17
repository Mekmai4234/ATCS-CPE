# สถาปัตยกรรมและข้อตกลงการเชื่อมต่อ

> เอกสารออกแบบเริ่มต้น: API, schema และ stack ด้านล่างยังไม่ได้ implement ต้องตกลงร่วมกันก่อนลงมือและปรับเอกสารให้ตรงกับโค้ด

## เทคโนโลยีที่เสนอ

Frontend: TypeScript + React/Next.js
Backend/AI: Python + FastAPI
Application data: SQLite สำหรับต้นแบบ
Knowledge data: ChromaDB
LLM และ Embeddings: ผ่าน provider adapter โดยเก็บ credentials ฝั่ง server
Background jobs: เริ่มจาก worker ที่อ่านงานจาก persistent job store ของ API; เลือก durable queue เพิ่มเมื่อการ deploy ต้องใช้

ล็อกเวอร์ชันใน manifest/lockfile หลังทดสอบความเข้ากันได้ ไม่ติดตั้งทุกหมวดเป็นบริการแยกโดยไม่จำเป็น
หมวด 03–06 อาจเป็น package ที่ API/worker เรียกใช้ใน Python environment เดียวกัน
เมื่อเพิ่ม source ให้สร้างชื่อ package ที่ถูกต้องภายในโฟลเดอร์เลขนำหน้า

## เส้นทางนำเข้า

01 Web -> 02 API: วางลิงก์
02: ตรวจ scope และบันทึก job
Worker -> 03: ดึง metadata และ transcript
Worker -> 04: แบ่งข้อความ ทำ embeddings และบันทึก index
02 -> 01: รายงานสถานะจริงของแต่ละคลิป

นำเข้าหลายคลิปไม่ต้องรอเสร็จพร้อมกัน คลิปที่ ready เริ่มถามตอบได้ก่อน

## เส้นทางคำตอบและ Agent

01 -> 02 -> 05 -> 04: ค้นหลักฐานภายใต้ scope
05 -> model adapter: สังเคราะห์และตรวจ citation
02 -> 01: ตอบพร้อม source records

งานค้นคว้า: 02 -> 06 -> เลือก search/read/analyze tools -> ตรวจความครอบคลุม -> เรียกซ้ำภายใต้งบ -> บันทึกผล
แบบทดสอบ/แฟลชการ์ดใช้เครื่องมือสร้าง learning artifact เดียวกันได้โดยไม่ต้องผ่าน agent loop ทุกครั้ง

## ข้อตกลง API ที่เสนอ

| Method / path | หน้าที่และข้อมูลสำคัญ |
|---|---|
| POST /api/videos/import | รับ urls[]; คืน jobs[] ที่มี job_id และ video_id เมื่อระบุได้ |
| GET /api/jobs/{job_id} | คืน stage, error_code, retryable และ progress เฉพาะเมื่อวัดได้ |
| GET /api/videos | คืนรายการคลิป กรอง channel/date/playlist เมื่อมี metadata |
| GET /api/videos/{video_id}/transcript | คืน segments พร้อมเวลาและภาษา |
| DELETE /api/videos/{video_id} | ลบข้อมูลที่ได้รับอนุญาตและ index ที่เกี่ยวข้อง |
| POST /api/chat | รับ question, conversation_id, scope; คืน answer, citations, status |
| POST /api/analysis | รับ summary/compare และ scope; คืนผลพร้อม coverage |
| POST /api/research | รับ goal, scope, level, days; คืน run_id |
| GET /api/research/{run_id} | คืน progress events, state และผลเมื่อเสร็จ |
| POST /api/learning-artifacts | รับ quiz/flashcards/study_plan และ scope; คืน artifact |
| GET /api/conversations/{id} | คืนประวัติที่มีสิทธิ์อ่าน |
| GET /api/learning-artifacts/{id} | คืนผลการเรียนรู้ที่บันทึกไว้ |
| GET /health | สถานะบริการสำหรับตรวจการ deploy |

scope ประกอบด้วย video_ids[], channel_ids[], playlist_ids[] และ date_from/date_to ตามที่รองรับ
ห้ามลดข้อจำกัด scope โดยเงียบ ๆ หากกรองไม่ได้ให้แจ้ง validation error
กรณีหลายผู้ใช้ ownership scope มาจาก session ฝั่ง server ไม่เชื่อ owner_id ที่ client ส่งมา

## สถานะ

Video import: queued -> fetching_transcript -> indexing -> ready
ทางออกอื่น: no_transcript, failed (มี error_code และ retryable)
การ retry ที่อนุญาตจะกลับเข้าคิวพร้อม attempt count
Research run: queued -> running -> completed / partial / failed / cancelled

Video จะ ready เมื่อ index ครบเท่านั้น ไม่ตีความว่าดึงชื่อและภาพปกได้แล้ว AI พร้อมใช้งาน

## ข้อมูลที่ใช้ร่วมกัน

TranscriptSegment: segment_id, video_id, text, start_seconds, duration_seconds, language, transcript_version
Chunk: chunk_id, video_id, transcript_version, text, segment_ids, start_seconds, end_seconds, embedding_version
Citation: citation_id, chunk_id, video_id, title, start_seconds, end_seconds, url
Job: job_id, video_id, stage, attempt_count, error_code, retryable, created_at, updated_at
LearningArtifact: artifact_id, type, scope, content, citations, coverage, created_at

เก็บความสัมพันธ์ channel/playlist กับวิดีโอและวันที่เผยแพร่เมื่อดึงได้
URL อ้างอิงสร้างจาก video ID และเวลา validated ไม่รับ URL ที่ model แต่งขึ้นเอง
คะแนนค้นคืนเป็นคะแนนจัดลำดับ ไม่ใช่เปอร์เซ็นต์ความถูกต้อง

## การสรุปให้ครบ

การถามเฉพาะจุดใช้ ranked retrieval ได้ แต่สรุปทุกคลิปต้องอ่านครบภายใน scope ผ่านการแบ่ง batch
เก็บจำนวนคลิปและ chunks ที่ประมวลผล แจ้ง partial coverage เมื่อข้อมูลไม่ครบ
ห้ามใช้คำว่า "ทุกครั้ง" หรือ "ครบทั้งหมด" ถ้ายังไม่ได้ค้นอย่างครอบคลุม

## การตั้งค่าและข้อมูล runtime

.env.example ที่ MiniProject root เป็นแม่แบบรวม
กำหนดให้ค่าพาธ runtime สัมพัทธ์อ้างจาก MiniProject root; แต่ละ entrypoint ต้อง resolve ตามกติกานี้
Frontend รับเฉพาะ NEXT_PUBLIC_API_BASE_URL ส่วนกุญแจ model และฐานข้อมูลอยู่ server
หากใช้ Next.js ให้เลือกวิธีโหลดค่า public ใน environment ของ frontend แล้วบันทึกวิธีจริงใน 01/step.txt
แยก data, application logs และ index ไว้ใน runtime/ ที่ถูก ignore
บทถอดเสียงและชื่อคลิปเป็นข้อมูลที่ไม่เชื่อถือ ห้ามนำไปใช้เป็นคำสั่งระบบหรือสิทธิ์เรียกเครื่องมือ
