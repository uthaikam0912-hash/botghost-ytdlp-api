# BotGhost + YouTube API (ตัวอย่างสำหรับทดสอบ)

ระบบนี้เป็น API แยกจาก BotGhost: BotGhost ส่ง URL ไปยัง `/download`, API ตอบ `job_id`, แล้ว BotGhost/ผู้ใช้เรียก `/status/<job_id>` เพื่อตรวจสอบผล

## ข้อจำกัดสำคัญ
- รองรับเฉพาะ URL ของ YouTube ในตัวอย่างนี้
- ใช้เฉพาะวิดีโอที่คุณเป็นเจ้าของหรือได้รับอนุญาตให้ดาวน์โหลด
- จำกัดความยาว 10 นาทีและขนาดไฟล์ 40 MB โดยประมาณ
- ไฟล์และสถานะอยู่ในพื้นที่ชั่วคราว/หน่วยความจำ และหายเมื่อเซิร์ฟเวอร์รีสตาร์ตหรือหลับ
- Render Free อาจหลับเมื่อไม่มีการใช้งาน และการดาวน์โหลดอาจล้มเหลว/หมดเวลา จึงเหมาะกับการทดลอง ไม่ใช่บริการ 24/7
- ห้ามรับโค้ด Python/Bash จากผู้ใช้แล้วนำไปรันตรง ๆ API นี้รับเฉพาะ URL และทำงานที่กำหนดไว้เท่านั้น

## 1) อัปโหลดโปรเจกต์ขึ้น GitHub
1. สร้าง repository ใหม่ชื่อ `botghost-ytdlp-api`
2. อัปโหลด `app.py`, `requirements.txt`, `Dockerfile` ไปไว้ที่ root ของ repository

## 2) Deploy บน Render
1. เปิด https://render.com แล้วสมัคร/เข้าสู่ระบบ
2. เลือก New > Web Service และเชื่อมต่อ repository
3. เลือก runtime แบบ Docker (อ่าน Dockerfile)
4. เลือก Free หากมีให้เลือก แล้วสร้าง service
5. ใน Environment เพิ่ม:
   - `API_TOKEN` = สุ่มคีย์ยาว ๆ ที่คาดเดายาก (เก็บเป็นความลับ)
   - `PUBLIC_BASE_URL` = URL ของ Web Service เช่น `https://ชื่อบริการ.onrender.com` (ไม่ต้องมี `/` ปิดท้าย)
6. Deploy แล้วเปิด `https://ชื่อบริการ.onrender.com/health` ต้องเห็น `{"ok":true}`

## 3) ตั้งค่า BotGhost
สร้าง Slash Command `/download` และเพิ่ม option แบบ Text ชื่อ `url` (required)
จากนั้นเพิ่ม Action: API Actions > Send an API Request
- Method: `POST`
- URL: `https://ชื่อบริการ.onrender.com/download`
- Header: `Authorization` = `Bearer ใส่ค่า_API_TOKEN_ที่ตั้งใน_Render`
- Header: `Content-Type` = `application/json`
- JSON Body: `{"url":"ค่าตัวแปร option url ของ BotGhost"}`
ในช่อง JSON Body ให้เลือกตัวแปร URL จากตัวแปร/เมนูของ BotGhost จริง ๆ อย่าพิมพ์ข้อความ placeholder ตามตัวอย่างลงไปตรง ๆ

API จะคืน `job_id` และ `status_url` ก่อน เพราะงานทำงานเบื้องหลัง จากนั้นให้ตั้ง BotGhost ตอบกลับด้วย `job_id` หรือ `status_url` และทำขั้นตอนตรวจสอบสถานะด้วย `GET https://ชื่อบริการ.onrender.com/status/ค่า_job_id`
เมื่อ `status` เป็น `done` จะมี `download_url`; ถ้าเป็น `processing` ให้ผู้ใช้ลองตรวจสอบสถานะอีกครั้งภายหลัง

ชื่อเมนูและวิธีอ้างอิงตัวแปรอาจต่างกันตามหน้าตา/แผน BotGhost ที่บัญชีคุณเห็น หากไม่พบช่อง Headers หรือ JSON Body ให้ส่งภาพหน้าจอของ Action นั้นมาเพื่อช่วยตั้งค่าตามหน้าจอจริง

## Security
อย่าโพสต์ `API_TOKEN` ใน Discord หรือในข้อความสาธารณะ และอย่ารับคำสั่งรันโค้ดอิสระจากผู้ใช้
