"""제출 문서(md)를 PDF로 만든다. 마크다운 → HTML → Chrome(Edge) 인쇄.

사용(저장소 루트에서):
    python docs/submission/build_pdfs.py            # 5개 문서 모두
    python docs/submission/build_pdfs.py 01 04      # 번호가 맞는 문서만

필요: python `markdown` 패키지, Chrome 또는 Edge. 결과는 docs/submission/*.pdf 에 쓰고
중간 HTML은 dist/pdf/ 에 둔다(Git 제외).

- `<!--FIG:이름-->` 자리에 figures/이름.html 조각을 넣는다. 이미지는 figures/ 의 PNG를 그대로 박아 넣는다.
- 화면 캡처(figures/shot-*.png, crop-*.png)는 실행 중인 화면에서 다시 찍어야 최신 상태가 된다.
"""

import base64
import re
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "dist" / "pdf"
FIG = HERE / "figures"
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
CSS = (FIG / "pdf.css").read_text(encoding="utf-8")


def inline_images(html: str) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        data = base64.b64encode((FIG / name).read_bytes()).decode()
        return f'src="data:image/png;base64,{data}"'

    return re.sub(r'src="figures/([^"]+\.png)"', repl, html)


def figure(name: str) -> str:
    return inline_images((FIG / f"{name}.html").read_text(encoding="utf-8"))


def build_html(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    text = re.sub(r"<!--FIG:([a-z0-9-]+)-->", lambda m: figure(m.group(1)), text)
    text = inline_images(text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "md_in_html"])
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<title>{md_path.stem}</title><style>{CSS}</style></head><body>{body}</body></html>"
    )


def to_pdf(html_path: Path, pdf_path: Path) -> None:
    browser = next(b for b in BROWSERS if Path(b).exists())
    subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    docs = sorted(HERE.glob("0[1-5]-*.md"))
    if argv:
        docs = [d for d in docs if d.name[:2] in argv]
    for md_path in docs:
        html_path = OUT / f"{md_path.stem}.html"
        html_path.write_text(build_html(md_path), encoding="utf-8")
        pdf_path = md_path.with_suffix(".pdf")
        to_pdf(html_path, pdf_path)
        try:
            import fitz  # PyMuPDF가 있으면 쪽수를 알려 준다

            pages = len(fitz.open(pdf_path))
        except ImportError:
            pages = "?"
        print(f"{pdf_path.name}: {pages}쪽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
