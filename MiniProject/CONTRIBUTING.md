# คู่มือทำงานร่วมกัน

## 1. รับสิทธิ์และดาวน์โหลด

เจ้าของ repository เชิญบัญชี GitHub ของสมาชิกผ่านเมนูจัดการ collaborators ใน Settings และสมาชิกต้องตอบรับคำเชิญก่อน push ได้ ชื่อเมนูอาจต่างกันตามชนิดบัญชี/สิทธิ์

สิทธิ์ collaborator ใช้กับ repository ทั้งหมด ไม่ใช่เฉพาะ MiniProject
เนื่องจาก repository นี้เป็น public การอ่านหรือ clone ไม่ต้องมีสิทธิ์เขียน แต่การ push ต้องได้รับสิทธิ์
หากต้องการจำกัดให้เขียนเฉพาะโปรเจกต์นี้จริง ๆ ให้แยก repository ในภายหลัง

ตัวอย่างคำสั่งใน terminal จากโฟลเดอร์ที่ต้องการเก็บงาน:

```powershell
git clone https://github.com/Mekmai4234/ATCS-CPE.git
cd ATCS-CPE
git fetch origin
git switch develop
git pull --ff-only origin develop
git switch -c feature/03-video-transcript
```

ตัวอย่างใช้หมวด 03 ให้เปลี่ยนชื่อ branch ตามงานจริง
หากมี checkout อยู่แล้ว ไม่ต้อง clone ซ้ำ และตรวจ `git status` ก่อนเปลี่ยน branch

## 2. อ่านงานและตั้งค่า

อ่าน README, docs/task_assignment.md และเอกสาร env.txt / step.txt / process.txt ของหมวดตนเอง
ตกลง schema กับเจ้าของหมวดที่ต้องเชื่อมต่อก่อนเริ่มเขียนโค้ด

จาก root ของ repository คัดลอกไฟล์ค่าตั้งค่าได้ด้วย:

```powershell
Copy-Item MiniProject/.env.example MiniProject/.env
```

ทำครั้งแรกเมื่อยังไม่มี .env เท่านั้น เติมค่าจริงบนเครื่องตนเอง
ไฟล์นี้เป็นแบบตั้งค่าที่วางแผนไว้ ยังไม่มีโปรแกรมอ่านค่าหรือคำสั่งรันแอป
เมื่อเพิ่ม source ให้ระบุ manifest, lockfile, working directory และคำสั่งรันจริงไว้ใน step.txt

## 3. ตั้งชื่อและจัดโค้ด

Branch ใช้ภาษาอังกฤษตัวพิมพ์เล็กและขีดกลาง:
- feature/01-video-library
- feature/02-import-api
- feature/03-video-transcript
- feature/04-vector-search
- feature/05-answer-citations
- feature/06-learning-agent
- feature/07-integration-checks
- fix/03-invalid-youtube-url
- docs/team-setup

ชื่อไฟล์ Python ใช้ snake_case; React component ใช้ PascalCase; ชื่อตัวแปร env ใช้ UPPER_SNAKE_CASE
โฟลเดอร์ 01–07 เป็นหมวดงาน ห้าม import ชื่อที่ขึ้นต้นด้วยตัวเลขเป็น Python package ตรง ๆ ให้สร้าง package ชื่อถูกต้องภายในหมวด แล้วกำหนด manifest ให้ชัดตอน implementation

Commit ใช้รูปแบบ เช่น:
- feat(ingestion): preserve transcript timestamps
- fix(rag): apply selected video filter
- docs(team): update task ownership

## 4. บันทึกและส่งงาน

ตรวจและ stage เฉพาะไฟล์งานของตนเอง ตัวอย่าง:

```powershell
git status
git diff -- MiniProject/03_video_ingestion
git add MiniProject/03_video_ingestion
git diff --cached
git commit -m "feat(ingestion): add timestamped transcript adapter"
git push -u origin feature/03-video-transcript
```

ตัวอย่าง commit ข้างบนใช้เมื่อเพิ่ม adapter จริงแล้ว สำหรับงานเอกสารให้ใช้ docs(...)
อย่าใช้ตัวอย่างนี้เพื่อ commit ว่า implementation เสร็จทั้งที่ยังมีเพียงเอกสาร

เปิด Pull Request โดยเลือก base เป็น develop และ compare เป็น branch ของตนเอง
ระบุปัญหา สิ่งที่เปลี่ยน วิธีทดสอบ ผลที่ได้ และข้อจำกัด ถ้ามี UI ให้แนบภาพ
ขอให้สมาชิกอีกคนตรวจแล้วจึงรวมงานตามที่ทีมตกลง

## 5. อัปเดตงานและแก้ conflict

ให้ commit หรือเก็บงานที่ค้างไว้ก่อน จากนั้นอยู่บน feature branch ของตนเองแล้วรัน:

```powershell
git fetch origin
git merge origin/develop
```

หากเกิด conflict ให้แก้ไฟล์ ตรวจผล stage ไฟล์ที่แก้แล้ว และ commit การ merge
หากไม่แน่ใจให้ประสานเจ้าของไฟล์ ห้าม force push เพื่อทับงานผู้อื่น

เมื่อ develop ผ่านการทดสอบรวมและการสาธิต ให้เปิด Pull Request จาก develop เข้า main
การตั้ง branch protection เป็นงานตั้งค่าเพิ่มเติม ยังไม่ได้เปิดด้วยการเพิ่มเอกสารนี้

## 6. เกณฑ์ก่อนส่ง

- งานตรงขอบเขตและ acceptance criteria ของหมวด
- บอกการตรวจสอบจริง ไม่อ้างว่าทดสอบผ่านหากยังไม่ได้รัน
- ปรับเอกสารเมื่อ API หรือวิธีเริ่มระบบเปลี่ยน
- ไม่มี .env, API key, ฐานข้อมูล runtime หรือข้อมูลอ่อนไหวใน diff
- แก้เฉพาะ MiniProject ยกเว้นทีมตกลงให้แก้ส่วนอื่น
- env.txt, step.txt และ process.txt ใช้ภาษาอังกฤษ
