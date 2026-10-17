# สถาปัตยกรรมและข้อตกลงการเชื่อมต่อ

> หมวด 02 มี implementation แล้ว ดู [ข้อตกลง API ที่ใช้งานจริง](backend_api_contract.md) และ [คู่มือรัน Backend](../02_api_backend/README.md)
> หมวด 01 และ 03–06 ยังเป็นข้อกำหนดออกแบบ การทดสอบ 02 ใช้ fixture แทนโมดูลเหล่านั้น

## เทคโนโลยีที่เสนอ

Frontend: TypeScript + React/Next.js
Backend/AI: Python + FastAPI
Application data: SQLite สำหรับต้นแบบ
Knowledge data: ChromaDB
LLM: Gemini ผ่าน Google GenAI SDK (`google-genai`) สำหรับ 05 และ 06
Embeddings: คงข้อเสนอ OpenAI `text-embedding-3-small` ของ 04 แยกจากโมเดลสร้างคำตอบ
เก็บ credentials ทั้งหมดฝั่ง server และเลือกโมเดลผ่าน configuration
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
| POST /api/analysis | รับ summary/compare และ scope; คืน job_id (202) ติดตามผลพร้อม coverage ผ่าน GET /api/jobs/{job_id} |
| POST /api/research | รับ goal, scope, level, days; คืน run_id |
| GET /api/research/{run_id} | คืน progress events, state และผลเมื่อเสร็จ |
| POST /api/learning-artifacts | รับ quiz/flashcards/study_plan และ scope; คืน job_id (202) แล้วอ่าน artifact_ids จากผลของ job |
| GET /api/conversations/{id} | คืนประวัติที่มีสิทธิ์อ่าน |
| GET /api/learning-artifacts/{id} | คืนผลการเรียนรู้ที่บันทึกไว้ |
| GET /health | สถานะบริการสำหรับตรวจการ deploy |

หมวด 02 เพิ่ม POST /api/jobs/{job_id}/cancel, POST /api/jobs/{job_id}/retry และ POST /api/research/{run_id}/cancel
แชตคืนคำตอบ JSON เมื่อเสร็จ หรือ 202 พร้อม job_id เมื่อมีงานกำลังทำ/retry; หน้าเว็บต้องรองรับทั้งสองกรณี
ขอบเขตรุ่นแรกต้องมี video_ids ที่เลือกชัดเจน รองรับ channel/date แบบ intersection และปฏิเสธ playlist filter ที่ยังไม่ implement
02 เป็นผู้ประสานงานเรียก 03 แล้ว 04 เพียงเส้นทางเดียว ไม่ให้ 03 เรียก indexing ซ้ำเอง
ตัวเชื่อม 04 ต้องรองรับ generation/version และป้องกัน stale worker ก่อน publish vectors ตามสัญญาในคู่มือ Backend

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

## การตั้งค่า Gemini และข้อตกลงเอกสาร

- `GEMINI_API_KEY` ใช้กับการสร้างคำตอบและ Agent; `OPENAI_API_KEY` ใช้เฉพาะเมื่อเลือก embedding adapter เดิม
- `LLM_MODEL=gemini-3.5-flash` สะท้อนชื่อรุ่นที่ผู้ใช้ระบุ เอกสาร Google ระบุว่าชื่อรุ่นนี้ deprecated และคำขอถูกส่งต่อไป `gemini-3.6-flash` ต้องตรวจสอบสิทธิ์และรุ่นที่ตอบกลับตอนเชื่อมต่อจริง
- แหล่งอ้างอิง: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash และ https://ai.google.dev/gemini-api/docs/libraries
- `MAX_CONTEXT_TOKENS` เป็นงบ input ของแอป ไม่ใช่จำนวน token สูงสุดของโมเดล; ต้องเผื่องบ output และข้อจำกัด provider
- `ENABLE_STREAMING=false` ใช้คำตอบ JSON ที่ตรวจแล้ว หากเพิ่ม streaming ต้องแยก provisional events กับ final answer ที่ผ่านการตรวจ
- chat/analysis response ใช้ `status`, `answer`, `citations[]`, `coverage` และ `provider_metadata`; chat เพิ่ม `conversation_id`
- `provider_metadata` เก็บชื่อรุ่นที่ร้องขอ และชื่อ/เวอร์ชันที่ provider ส่งกลับเมื่อมี พร้อม usage และ latency ที่วัดได้
- การวางงานนานต้องใช้ persistent job/run records; การเก็บประวัติสนทนาต้อง durable ส่วน telemetry ส่งแบบ asynchronous ได้
- เอกสาร `step.txt` อธิบาย runtime workflow ส่วนคำสั่งติดตั้ง/เริ่มแอปจริงจะเพิ่มเมื่อมี source และ manifests
