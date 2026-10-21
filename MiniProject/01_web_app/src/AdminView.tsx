import { useEffect, useState } from 'react';
import type { AdminSection, AdminSnapshot, MemberSession, SessionPort } from './session';
import { BuddyLogo, ForestBackdrop, Mascot } from './Forest';
import { ApiError } from './api';

const names: Record<AdminSection, string> = {
  overview: 'ภาพรวม',
  members: 'สมาชิก',
  videos: 'วิดีโอ',
  jobs: 'งานประมวลผล',
  audit: 'ประวัติการจัดการ',
};
export default function AdminView({
  session,
  port,
  onHome,
  onLogout,
  onSessionExpired,
}: {
  session: MemberSession;
  port: SessionPort;
  onHome: () => void;
  onLogout: () => void;
  onSessionExpired: () => void;
}) {
  const [section, setSection] = useState<AdminSection>(session.adminSections[0] || 'overview');
  const [data, setData] = useState<AdminSnapshot | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void port
      .admin(session, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted && error instanceof ApiError && error.status === 401) {
          setData(null);
          onSessionExpired();
          return;
        }
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'โหลดข้อมูลไม่สำเร็จ');
      });
    return () => controller.abort();
  }, [port, session, onSessionExpired]);
  async function changeStatus(id: string, status: 'active' | 'suspended') {
    setPending(true);
    setError('');
    try {
      await port.setMemberStatus(session, id, status);
      setData(await port.admin(session));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setData(null);
        onSessionExpired();
        return;
      }
      setError(error instanceof Error ? error.message : 'เปลี่ยนสถานะไม่สำเร็จ');
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="admin-shell">
      <ForestBackdrop />
      <aside className="admin-sidebar">
        <BuddyLogo onClick={onHome} />
        <h2>จัดการระบบ</h2>
        <nav aria-label="เมนูผู้ดูแล">
          {session.adminSections.map((key) => (
            <button
              key={key}
              aria-current={section === key ? 'page' : undefined}
              className={section === key ? 'active' : ''}
              onClick={() => setSection(key)}
            >
              {names[key]}
            </button>
          ))}
        </nav>
        <Mascot />
      </aside>
      <main className="admin-main">
        <div className="admin-top">
          <button className="secondary" onClick={onHome}>
            กลับพื้นที่เรียนรู้
          </button>
          <button className="profile-pill" onClick={onLogout}>
            ผู้ดูแล · ออกจากระบบ
          </button>
        </div>
        {port.demo && (
          <div className="demo-banner">DEMO · ข้อมูลสมาชิกและการจัดการจำลอง ไม่เชื่อมระบบจริง</div>
        )}
        <section className="admin-card">
          <span className="eyebrow">RAG BUDDY ADMINISTRATION</span>
          <h1>{names[section]}</h1>
          <p className="admin-subtitle">จัดการสมาชิกและสถานะระบบ โดยไม่เปิดเนื้อหาบทสนทนาส่วนตัว</p>
          {error && (
            <p role="alert" className="notice error">
              {error}
            </p>
          )}
          {!data && !error && <p role="status">กำลังโหลดข้อมูล…</p>}
          {data && (
            <>
              {section === 'overview' && (
                <div className="admin-stats">
                  <article>
                    <strong>{data.members.length}</strong>
                    <span>สมาชิก</span>
                  </article>
                  <article>
                    <strong>{data.videos.length}</strong>
                    <span>วิดีโอในระบบ</span>
                  </article>
                  <article>
                    <strong>
                      {data.jobs.filter((job) => ['queued', 'running'].includes(job.state)).length}
                    </strong>
                    <span>งานที่กำลังทำ</span>
                  </article>
                </div>
              )}
              {section === 'members' && (
                <>
                  <label className="member-search">
                    ค้นหาสมาชิก
                    <input
                      type="search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="ค้นหาชื่อหรืออีเมล"
                    />
                  </label>
                  <div className="table-scroll">
                    <table>
                      <caption className="visually-hidden">รายชื่อและสถานะสมาชิก</caption>
                      <thead>
                        <tr>
                          <th scope="col">ชื่อผู้ใช้</th>
                          <th scope="col">บทบาท</th>
                          <th scope="col">สถานะ</th>
                          <th scope="col">จัดการ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.members
                          .filter((member) =>
                            `${member.name} ${member.email}`
                              .toLocaleLowerCase()
                              .includes(query.toLocaleLowerCase()),
                          )
                          .map((member) => (
                            <tr key={member.id}>
                              <td>
                                <strong>{member.name}</strong>
                                <small>{member.email}</small>
                              </td>
                              <td>
                                <span className={`role-chip ${member.role}`}>
                                  {member.role === 'admin' ? 'ผู้ดูแล' : 'สมาชิก'}
                                </span>
                              </td>
                              <td>
                                <span className={`member-status ${member.status}`}>
                                  {member.status === 'active' ? 'ใช้งานอยู่' : 'ถูกระงับ'}
                                </span>
                              </td>
                              <td>
                                {member.role !== 'admin' && (
                                  <button
                                    className="secondary"
                                    disabled={pending}
                                    onClick={() =>
                                      void changeStatus(
                                        member.id,
                                        member.status === 'active' ? 'suspended' : 'active',
                                      )
                                    }
                                  >
                                    {member.status === 'active' ? 'ระงับบัญชี' : 'เปิดใช้บัญชี'}
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {section === 'videos' && (
                <div className="admin-records">
                  {data.videos.length ? (
                    data.videos.map((video) => (
                      <article key={video.id}>
                        <strong>{video.title}</strong>
                        <span>{video.status}</span>
                      </article>
                    ))
                  ) : (
                    <p>ยังไม่มีวิดีโอในรายการระบบ</p>
                  )}
                </div>
              )}
              {section === 'jobs' && (
                <div className="admin-records">
                  {data.jobs.length ? (
                    data.jobs.map((job) => (
                      <article key={job.id}>
                        <strong>{job.kind}</strong>
                        <span>{job.state}</span>
                      </article>
                    ))
                  ) : (
                    <p>ไม่มีงานประมวลผลในรายการ</p>
                  )}
                </div>
              )}
              {section === 'audit' && (
                <div className="admin-records">
                  {data.audit.length ? (
                    data.audit.map((event) => (
                      <article key={event.id}>
                        <strong>
                          {event.action} · {event.target}
                        </strong>
                        <time>{new Date(event.timestamp).toLocaleString('th-TH')}</time>
                      </article>
                    ))
                  ) : (
                    <p>ยังไม่มีประวัติการจัดการ</p>
                  )}
                </div>
              )}
            </>
          )}
        </section>
      </main>
    </div>
  );
}
