// Deterministic app help, not a video answer or an AI-provider request.
export function smallTalkReply(input: string): string | null {
  const text = input
    .normalize('NFC')
    .trim()
    .toLowerCase()
    .replace(/[!?！？.。]+$/g, '')
    .trim();
  if (/^(สวัสดี(?:ครับ|ค่ะ|คะ)?|หวัดดี(?:ครับ|ค่ะ)?|hello|hi|hey)$/.test(text))
    return 'สวัสดีครับ ผม Buddy ผู้ช่วยของ Video Buddy ยินดีที่ได้คุยด้วยครับ';
  if (
    /^(คุณ(?:ชื่ออะไร|คือใคร|ทำงานเกี่ยวกับอะไร|ทำอะไรได้บ้าง)|เธอคือใคร|ทำอะไรได้บ้าง|who are you|what can you do)$/.test(
      text,
    )
  )
    return 'ผมชื่อ Buddy ช่วยถามตอบจากคลิป YouTube สรุปเนื้อหา และสร้างแบบฝึกหัดพร้อมแหล่งอ้างอิงครับ ถ้าจะถามเรื่องในคลิป เลือกคลิปก่อนส่งได้เลย';
  if (/^(ขอบคุณ(?:ครับ|ค่ะ)?|thanks|thank you)$/.test(text))
    return 'ยินดีครับ มีอะไรให้ Buddy ช่วยอีกบอกได้เลย';
  if (/^(สบายดีไหม|เป็นไงบ้าง|how are you)$/.test(text))
    return 'Buddy พร้อมช่วยครับ วันนี้อยากคุยหรือเรียนรู้เรื่องอะไรดี';
  return null;
}
