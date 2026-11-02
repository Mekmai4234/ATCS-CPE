# Transcript sources

Five user-supplied Thai transcripts, copied from the user's local transcript folder.
Each timed passage uses `[MM:SS] - [MM:SS] text`. The final passage in each file has
`[ไม่ระบุ]` as its end because a verified ending time was not supplied.

These are source documents, not verified audio alignments. Most ending times were
derived from the next passage's start. Keep that provenance when importing them.
Do not invent timestamps for the metadata headers or unknown final endings.

| Document | YouTube video ID |
| --- | --- |
| DICEBLUE 'รอ SIS (TER)' OFFICIAL MV.txt | C0DXctGPWxw |
| ดีใจที่ตรงนั้นไม่ใช่เรา - Only Monday [Official MV].txt | B-zaXo-skGo |
| เอากาชาที่ขายมาเปิดเล่น...จะกำไรแบบในเกมไหม  ร้านเกลือ TCG ในชีวิตจริง EP.4.txt | NZImGB4O-X4 |
| RAG คืออะไร เทคนิคที่ช่วยทำ AI ChatBot ให้ AI เข้าใจธุรกิจของคุณ.txt | cWVse_LuFO0 |
| RAG คืออะไร ทำให้ Gen AI เก่งขึ้นได้อย่างไร มาลองด้วย GPTs  Prompt Expert.txt | f0SQzjp3QzM |

Mapping above reflects the existing library and must be validated by the future
importer. File names are not stable identifiers; use an explicit manifest and file
hashes in that implementation.

Adding these documents to Git does not activate ingestion or change chat behavior.
The proposed implementation is documented separately in the user's Youtube Fix
folder. Until implemented, the application continues to use its existing database
and retrieval path.
