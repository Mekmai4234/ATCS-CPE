# ตารางแบ่งงานทีม

ยังไม่กำหนดชื่อสมาชิกหรือระบุว่ามีงานเสร็จแล้ว ให้ทีมเติมชื่อ GitHub และลิงก์ Issue/PR เมื่อเริ่มทำจริง
สถานะเริ่มต้นของทุกแถวคือ Planned

| หมวด | ผู้รับผิดชอบ | ผลงานที่ต้องส่ง | Dependency | สถานะ | Issue / PR |
|---|---|---|---|---|---|
| 01_web_app | ยังไม่ระบุ | หน้านำเข้า คลังคลิป แชต อ้างอิง และหน้าสื่อเรียนรู้ | API contract ของ 02; ใช้ mock ที่ติดป้ายได้ช่วงแรก | Planned | — |
| 02_api_backend | ยังไม่ระบุ | schema, API, job store/worker, history, artifacts | ตกลง interface กับ 03–06 | Planned | — |
| 03_video_ingestion | ยังไม่ระบุ | URL parser, metadata/transcript adapter, timestamp records | job/schema ของ 02 | Planned | — |
| 04_rag_knowledge | ยังไม่ระบุ | chunking, indexing, scoped retrieval, coverage enumeration | transcript schema ของ 03 | Planned | — |
| 05_ai_answers_analysis | ยังไม่ระบุ | grounded answers, citations, summaries, comparisons | evidence contract ของ 04 | Planned | — |
| 06_research_learning_agent | ยังไม่ระบุ | bounded agent loop, study plan, quizzes, flashcards | tools จาก 04–05 และ persistence ของ 02 | Planned | — |
| 07_testing_deployment | ยังไม่ระบุ | fixtures, evaluation, integration checks, deployment guide | acceptance criteria ทุกหมวด | Planned | — |

## ลำดับการทำงาน

1. ตกลง schema และ API ระหว่าง 01–06 โดยให้ 02 บันทึกสัญญาเชื่อมต่อ
2. 01 เริ่ม UI ด้วย mock ที่ระบุชัด ส่วน 02 และ 03 ทำเส้นทางนำเข้า
3. เชื่อม 03 -> 04 -> 05 จนถามตอบพร้อมหลักฐานได้จริง
4. เพิ่มการวิเคราะห์หลายคลิปและ 06 Agent/สื่อการเรียนรู้
5. 07 วางกรณีทดสอบตั้งแต่ต้น และประเมินระบบรวมก่อนส่งเข้า main

## เกณฑ์สถานะ

Planned: กำหนดขอบเขตแล้ว
In Progress: มีผู้รับผิดชอบและกำลังพัฒนา
In Review: มี Pull Request พร้อมผลตรวจสอบ
Done: ผ่าน acceptance criteria และรวมเข้า develop
Released: รวมเข้า main และมีผลสาธิต/ตรวจสอบของรุ่นนั้น

## ตัวอย่างขนาดงานที่ควรเปิด PR

- 03: รองรับ watch URL และ short URL พร้อมทดสอบลิงก์ผิด
- 04: เก็บ time bounds ของ chunk พร้อมตรวจว่าอ้างกลับ transcript ได้
- 05: ปฏิเสธ citation ที่ไม่อยู่ในหลักฐานที่ค้นพบ
- 06: หยุด agent เมื่อครบ step budget พร้อมบันทึก partial result

หนึ่งคนรับได้หลายหมวด และหนึ่งหมวดแบ่งหลาย PR ได้ตามขนาดงาน ไม่จำเป็นต้องมีสมาชิกเจ็ดคน
