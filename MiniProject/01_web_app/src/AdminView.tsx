import { useEffect, useState } from 'react';
import type { AdminSection, AdminSnapshot, MemberSession, SessionPort } from './session';
import { BuddyLogo } from './Forest';
import { BuddyArt } from './BuddyArt';
import { UiIcon } from './Visuals';
import { ApiError } from './api';
import './secondary-v5.css';

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
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void port
      .admin(session, controller.signal, query, offset)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((error) => {
        if (
          !controller.signal.aborted &&
          error instanceof ApiError &&
          [401, 403].includes(error.status || 0)
        ) {
          setData(null);
          onSessionExpired();
          return;
        }
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'โหลดข้อมูลไม่สำเร็จ');
      });
    return () => controller.abort();
  }, [port, session, onSessionExpired, query, offset]);
  async function changeStatus(
    id: string,
    change: { status?: 'active' | 'suspended'; role?: 'user' | 'admin' },
  ) {
    setPending(true);
    setError('');
    try {
      if (change.status) await port.setMemberStatus(session, id, change.status);
      if (change.role) await port.setMemberRole?.(session, id, change.role);
      setData(await port.admin(session, undefined, query, offset));
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status || 0)) {
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
    <div className="admin-shell vb-admin">
      <aside className="admin-sidebar">
        <BuddyLogo onClick={onHome} />
        <nav className="vb-admin-workspace-nav" aria-label="เมนูหลัก">
          <button onClick={onHome}>
            <UiIcon name="home" />
            หน้าแรก
          </button>
          <a href="/library">
            <UiIcon name="library" />
            วิดีโอของฉัน
          </a>
          <a href="/learning">
            <UiIcon name="learn" />
            สรุปและแบบฝึกหัด
          </a>
          <a href="/history">
            <UiIcon name="clock" />
            ประวัติแชท
          </a>
        </nav>
        <div className="vb-admin-side-bottom">
          <a href="/help">
            <UiIcon name="help" />
            ช่วยเหลือ
          </a>
          <span className="vb-admin-location">
            <UiIcon name="learn" />
            จัดการระบบ
          </span>
          <div className="vb-admin-profile">
            <span>{session.member.name.slice(0, 1)}</span>
            <strong>{session.member.name}</strong>
          </div>
        </div>
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
        <nav className="vb-admin-tabs" aria-label="เมนูผู้ดูแล">
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
        <section className="admin-card">
          <div className={`vb-admin-hero vb-admin-hero-${section}`}>
            <div className="vb-admin-hero-copy">
              <h1>{names[section]}</h1>
              {section === 'overview' && data && (
                <div className="admin-stats">
                  <article>
                    <strong>
                      {data.stats
                        ? data.stats.jobs.running || 0
                        : data.jobs?.filter((job) => job.state === 'running').length || 0}
                    </strong>
                    <span>กำลังทำงาน</span>
                  </article>
                  <article>
                    <strong>
                      {data.stats
                        ? data.stats.jobs.queued || 0
                        : data.jobs?.filter((job) => job.state === 'queued').length || 0}
                    </strong>
                    <span>รอคิว</span>
                  </article>
                  <article>
                    <strong>{data.stats?.users ?? data.members.length}</strong>
                    <span>สมาชิก</span>
                  </article>
                </div>
              )}
              {section === 'members' && (
                <label className="member-search">
                  ค้นหาสมาชิก
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setOffset(0);
                    }}
                    placeholder="ค้นหาชื่อหรืออีเมล"
                  />
                </label>
              )}
            </div>
            <div className="vb-admin-art">
              <BuddyArt
                pose={
                  section === 'members'
                    ? 'members'
                    : section === 'videos'
                      ? 'library'
                      : section === 'jobs'
                        ? 'states'
                        : 'admin'
                }
              />
            </div>
          </div>
          {error && (
            <p role="alert" className="notice error">
              {error}
            </p>
          )}
          {!data && !error && <p role="status">กำลังโหลดข้อมูล…</p>}
          {data && (
            <>
              {(section === 'members' || section === 'overview') && (
                <>
                  {section === 'overview' && (
                    <div className="vb-admin-table-heading">
                      <h2>สมาชิก</h2>
                      {session.adminSections.includes('members') && (
                        <button className="text-button" onClick={() => setSection('members')}>
                          ดูทั้งหมด <UiIcon name="arrow" />
                        </button>
                      )}
                    </div>
                  )}
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
                                <div className="vb-admin-person">
                                  <span className="vb-admin-avatar" aria-hidden="true">
                                    {member.name.slice(0, 1)}
                                  </span>
                                  <div>
                                    <strong>{member.name}</strong>
                                    <small title={member.email}>{member.email}</small>
                                    <span className="vb-admin-mobile-role">
                                      {member.role === 'admin' ? 'ผู้ดูแล' : 'สมาชิก'}
                                    </span>
                                  </div>
                                </div>
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
                                {section === 'overview' ? (
                                  session.adminSections.includes('members') && (
                                    <button
                                      className="secondary"
                                      onClick={() => setSection('members')}
                                    >
                                      จัดการ <UiIcon name="arrow" size={16} />
                                    </button>
                                  )
                                ) : (
                                  <div className="vb-admin-actions">
                                    {(member.role !== 'admin' || port.setMemberRole) && (
                                      <button
                                        className="secondary"
                                        disabled={pending}
                                        onClick={() =>
                                          void changeStatus(member.id, {
                                            status:
                                              member.status === 'active' ? 'suspended' : 'active',
                                          })
                                        }
                                      >
                                        {member.status === 'active' ? 'ระงับบัญชี' : 'เปิดใช้บัญชี'}
                                      </button>
                                    )}
                                    {port.setMemberRole && (
                                      <button
                                        className="secondary"
                                        disabled={pending}
                                        onClick={() =>
                                          void changeStatus(member.id, {
                                            role: member.role === 'admin' ? 'user' : 'admin',
                                          })
                                        }
                                      >
                                        {member.role === 'admin'
                                          ? 'เปลี่ยนเป็นสมาชิก'
                                          : 'ตั้งเป็นผู้ดูแล'}
                                      </button>
                                    )}
                                  </div>
                                )}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {section === 'members' && data.memberPage && (
                    <div className="member-pagination">
                      <button
                        className="secondary"
                        disabled={!offset || pending}
                        onClick={() => setOffset(Math.max(0, offset - data.memberPage!.limit))}
                      >
                        หน้าก่อนหน้า
                      </button>
                      <span>หน้า {Math.floor(offset / data.memberPage.limit) + 1}</span>
                      <button
                        className="secondary"
                        disabled={!data.memberPage.hasMore || pending}
                        onClick={() => setOffset(offset + data.memberPage!.limit)}
                      >
                        หน้าถัดไป
                      </button>
                    </div>
                  )}
                </>
              )}
              {section === 'videos' && data.videos && (
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
              {section === 'jobs' && data.jobs && (
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
              {section === 'audit' && data.audit && (
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
