import { useState, type FormEvent } from "react";
import { Activity, ChevronRight, Eye, EyeOff } from "lucide-react";
import { Button } from "../components/Button";

export type Session = { approverId: string; token: string };

export function LoginPage({
  onLogin,
}: {
  onLogin: (approverId: string, token: string) => Promise<void>;
}) {
  const [approverId, setApproverId] = useState("");
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!approverId.trim() || !token) {
      setError("담당자 ID와 인증 토큰을 모두 입력하세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onLogin(approverId.trim(), token);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "로그인을 확인하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-logo">
          <span className="brand-mark">
            <Activity size={24} aria-hidden="true" />
          </span>
          <span>제주 에너지</span>
        </div>
        <h1 id="login-title" className="sr-only">
          담당자 로그인
        </h1>

        <form className="login-form" onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="login-id">담당자 ID</label>
            <input
              id="login-id"
              autoComplete="username"
              value={approverId}
              onChange={(e) => setApproverId(e.target.value)}
              aria-invalid={error ? true : undefined}
            />
          </div>
          <div className="field">
            <label htmlFor="login-token">인증 토큰</label>
            <div className="login-secret">
              <input
                id="login-token"
                type={showToken ? "text" : "password"}
                autoComplete="current-password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                aria-invalid={error ? true : undefined}
              />
              <button
                type="button"
                className="login-eye"
                onClick={() => setShowToken((v) => !v)}
                aria-label={showToken ? "토큰 숨기기" : "토큰 보기"}
                aria-pressed={showToken}
              >
                {showToken ? (
                  <Eye size={20} aria-hidden="true" />
                ) : (
                  <EyeOff size={20} aria-hidden="true" />
                )}
              </button>
            </div>
          </div>
          {error && (
            <p role="alert" className="login-error">
              {error}
            </p>
          )}
          <Button type="submit" className="login-submit" busy={busy}>
            로그인
          </Button>
          <div className="login-meta">
            <span>로그인 정보는 이 탭의 메모리에만 보관됩니다.</span>
            <button
              type="button"
              className="login-link"
              aria-expanded={helpOpen}
              aria-controls="login-help"
              onClick={() => setHelpOpen((v) => !v)}
            >
              토큰 확인 방법
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </div>
          {helpOpen && (
            <p id="login-help" className="login-help">
              담당자 ID는 서버의 <code>APPROVER_ID</code>, 인증 토큰은{" "}
              <code>APPROVER_TOKEN</code> 값입니다(<code>backend/.env</code>).
              관리자에게 받은 값을 입력하세요.
            </p>
          )}
        </form>

        <p className="login-foot">
          계정이 없으신가요?{" "}
          <strong>관리자에게 담당자 토큰을 요청하세요.</strong>
        </p>
      </section>
    </div>
  );
}
