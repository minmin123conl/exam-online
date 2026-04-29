import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AttemptResult } from "../api";

export default function StudentResult() {
  const { attemptId } = useParams();
  const [res, setRes] = useState<AttemptResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const stored = sessionStorage.getItem(`result_${attemptId}`);
    if (stored) {
      setRes(JSON.parse(stored));
      return;
    }
    api.getResult(Number(attemptId)).then(setRes).catch((e) => setErr((e as Error).message));
  }, [attemptId]);

  if (err) return <div className="container"><div className="error">{err}</div></div>;
  if (!res) return <div className="container muted">Đang tải kết quả…</div>;

  const duration = Math.max(1, Math.round(res.duration_seconds / 60));

  return (
    <div className="container">
      <div className="score-hero">
        <div className="big">{res.score_on_ten}/10</div>
        <div className="label">
          {res.student_name}
          {res.student_class ? ` — ${res.student_class}` : ""}
        </div>
        <div className="label">
          Đúng <strong>{res.num_correct}</strong> trong số <strong>{res.num_questions}</strong> câu •{" "}
          Điểm thô {res.score.toFixed(2)}/{res.total_points.toFixed(2)} • Làm trong {duration} phút
        </div>
        <div style={{ marginTop: 16, display: "flex", justifyContent: "center", gap: 8 }}>
          <Link to={`/leaderboard/${res.exam_id}`} className="btn secondary">
            🏆 Xem bảng xếp hạng
          </Link>
          <Link to="/" className="btn secondary">
            Về trang chủ
          </Link>
        </div>
      </div>

      <div className="card">
        <h3>Bảng trả lời chi tiết</h3>
        <div className="muted" style={{ marginBottom: 10 }}>Màu xanh: đáp án đúng. Màu đỏ: đáp án bạn chọn sai.</div>
        <div className="stack">
          {res.details.map((d, i) => (
            <div key={d.question_id} className="card" style={{ padding: 12 }}>
              <div>
                <span className="question-number">Câu {i + 1}</span>{" "}
                {d.is_correct ? (
                  <span className="badge success">✓ Đúng (+{d.earned.toFixed(2)})</span>
                ) : (
                  <span className="badge danger">✗ Sai (+{d.earned.toFixed(2)}/{d.points})</span>
                )}{" "}
                {d.section && <span className="muted">{d.section}</span>}
              </div>
              <div className="question-text">{d.question}</div>
              {d.type === "mc" && d.options && (
                <div>
                  {Object.entries(d.options).map(([letter, text]) => {
                    const isCorrect = d.correct === letter;
                    const isYour = d.your_answer === letter;
                    return (
                      <div
                        key={letter}
                        className={`option ${isCorrect ? "correct-highlight" : isYour && !isCorrect ? "wrong-highlight" : ""}`}
                      >
                        <span className="letter">{letter}.</span>
                        <span style={{ flex: 1 }}>{text}</span>
                        {isCorrect && <span className="badge success">Đáp án đúng</span>}
                        {isYour && !isCorrect && <span className="badge danger">Bạn chọn</span>}
                      </div>
                    );
                  })}
                </div>
              )}
              {d.type === "tf" && d.statements && (
                <div>
                  {Object.entries(d.statements).map(([letter, text]) => {
                    const correct = (d.correct as Record<string, boolean>)[letter];
                    const yoursMap = d.your_answer as Record<string, boolean>;
                    const yours = yoursMap?.[letter];
                    const ok = correct === yours;
                    return (
                      <div
                        key={letter}
                        className={`option ${ok ? "correct-highlight" : "wrong-highlight"}`}
                      >
                        <span className="letter">{letter})</span>
                        <span style={{ flex: 1 }}>{text}</span>
                        <span className="muted" style={{ whiteSpace: "nowrap" }}>
                          Đáp án: <strong>{correct ? "Đúng" : "Sai"}</strong>
                        </span>
                        <span
                          className={ok ? "explain-correct" : "explain-wrong"}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          Bạn: {yours === undefined ? "—" : yours ? "Đúng" : "Sai"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
