import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, getToken, setToken, type ExamSummary } from "../api";

export default function AdminDashboard() {
  const nav = useNavigate();
  const [exams, setExams] = useState<ExamSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newDuration, setNewDuration] = useState(45);

  async function load() {
    try {
      const list = await api.listExams();
      setExams(list);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    if (!getToken()) {
      nav("/admin/login");
      return;
    }
    load();
  }, [nav]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const exam = await api.createExam({
        title: newTitle,
        description: newDesc,
        duration_minutes: newDuration,
        is_active: true,
        show_leaderboard: true,
      });
      setShowCreate(false);
      setNewTitle("");
      setNewDesc("");
      setNewDuration(45);
      nav(`/admin/exams/${exam.id}`);
    } catch (e) {
      alert((e as Error).message);
    }
  }

  async function remove(id: number) {
    if (!confirm("Xoá đề thi này và toàn bộ mã thi + kết quả?")) return;
    await api.deleteExam(id);
    load();
  }

  async function duplicate(id: number) {
    await api.duplicateExam(id);
    load();
  }

  function logout() {
    setToken(null);
    nav("/admin/login");
  }

  return (
    <div className="container">
      <div className="toolbar">
        <h2 style={{ margin: 0, flex: 1 }}>Quản trị đề thi</h2>
        <button className="btn" onClick={() => setShowCreate(true)}>+ Tạo đề mới</button>
        <button className="btn secondary" onClick={logout}>Đăng xuất</button>
      </div>

      {err && <div className="card"><div className="error">{err}</div></div>}

      {showCreate && (
        <div className="card">
          <h3>Tạo đề thi mới</h3>
          <form onSubmit={create}>
            <div className="field">
              <label>Tên đề</label>
              <input className="input" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} autoFocus />
            </div>
            <div className="field">
              <label>Mô tả</label>
              <textarea value={newDesc} onChange={(e) => setNewDesc(e.target.value)} />
            </div>
            <div className="field">
              <label>Thời gian làm bài (phút)</label>
              <input
                className="input"
                type="number"
                min={1}
                value={newDuration}
                onChange={(e) => setNewDuration(Number(e.target.value))}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="submit" className="btn">Tạo</button>
              <button type="button" className="btn secondary" onClick={() => setShowCreate(false)}>
                Huỷ
              </button>
            </div>
          </form>
        </div>
      )}

      {exams === null ? (
        <div className="muted">Đang tải…</div>
      ) : exams.length === 0 ? (
        <div className="card muted">Chưa có đề thi nào. Tạo đề đầu tiên!</div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Tên đề</th>
                <th>Số câu</th>
                <th>Mã thi</th>
                <th>Lượt làm</th>
                <th>Thời gian</th>
                <th>Trạng thái</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {exams.map((e) => (
                <tr key={e.id}>
                  <td>
                    <Link to={`/admin/exams/${e.id}`} style={{ fontWeight: 600 }}>
                      {e.title}
                    </Link>
                    <div className="muted" style={{ fontSize: 12 }}>{e.description}</div>
                  </td>
                  <td>{e.num_questions}</td>
                  <td>
                    {e.num_codes_used}/{e.num_codes}
                  </td>
                  <td>{e.num_attempts}</td>
                  <td>{e.duration_minutes} phút</td>
                  <td>
                    {e.is_active ? (
                      <span className="badge success">Đang mở</span>
                    ) : (
                      <span className="badge warning">Đã khoá</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <Link to={`/admin/exams/${e.id}`} className="btn sm secondary">Sửa</Link>
                      <button className="btn sm secondary" onClick={() => duplicate(e.id)}>
                        Nhân bản
                      </button>
                      <button className="btn sm danger" onClick={() => remove(e.id)}>
                        Xoá
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
