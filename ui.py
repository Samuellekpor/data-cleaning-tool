from __future__ import annotations

from html import escape

import streamlit as st

EXCEL_REPORT_AUTOMATOR_URL = "https://github.com/Samuellekpor/excel-report-automator"

_SEV_TOKENS = frozenset({"high", "medium", "low"})
_PILLAR_TOKENS = frozenset({"completeness", "uniqueness", "consistency"})


def _css_token(value: str | None, allowed: frozenset[str], fallback: str) -> str:
    token = (value or "").strip().lower()
    return token if token in allowed else fallback

FONTS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,400;0,500;0,600;1,400&family=Syne:wght@500;600;700;800&display=swap" rel="stylesheet">
"""

CSS = r"""
<style>
  :root {
    --era-bg: #080706;
    --era-ink: #F6F0E6;
    --era-muted: rgba(246,240,230,0.58);
    --era-hair: rgba(255,255,255,0.10);
    --era-shell: rgba(255,236,210,0.05);
    --era-core: #100E0C;
    --era-teal: #E4B363;
    --era-violet: #C9A0B8;
    --era-radius: 1.1rem;
    --era-radius-in: 0.82rem;
    --era-chip: 0.65rem;
    --era-ease: cubic-bezier(0.32, 0.72, 0, 1);
  }

  html, body, .stApp, [data-testid="stAppViewContainer"] {
    background: var(--era-bg) !important;
    color: var(--era-ink) !important;
    font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif !important;
  }

  .stApp { min-height: 100dvh; }

  .stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 0;
    background:
      radial-gradient(ellipse 55% 40% at 12% -10%, rgba(228,179,99,0.18), transparent 58%),
      radial-gradient(ellipse 45% 38% at 92% 8%, rgba(201,160,184,0.16), transparent 55%),
      radial-gradient(ellipse 40% 30% at 70% 95%, rgba(228,179,99,0.07), transparent 60%);
  }

  .stApp::after {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0.035;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)'/%3E%3C/svg%3E");
  }

  header[data-testid="stHeader"] { background: transparent !important; }
  [data-testid="stToolbar"] { right: 1.25rem !important; }
  .stDeployButton,
  .stAppDeployButton,
  [data-testid="stAppDeployButton"],
  [data-testid="stDecoration"] { display: none !important; }

  .block-container {
    padding: 4.5rem 2.4rem 6rem !important;
    max-width: 1180px !important;
    position: relative;
    z-index: 2;
  }

  @media (max-width: 768px) {
    .block-container {
      padding: 2rem 1rem 4rem !important;
      width: 100% !important;
    }
  }

  h1, h2, h3, .era-display {
    font-family: "Syne", sans-serif !important;
    letter-spacing: -0.045em !important;
    font-weight: 700 !important;
    color: var(--era-ink) !important;
  }

  p, label, li, .stMarkdown, [data-testid="stCaption"] {
    font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif !important;
  }

  [data-testid="stBaseButton-headerNoPadding"],
  [data-testid="stBaseButton-header"],
  [data-testid="stSidebarCollapsedControl"] button,
  [data-testid="collapsedControl"] button {
    text-transform: none !important;
    letter-spacing: normal !important;
    font-size: 1.25rem !important;
    padding: 0.35rem !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
  }

  .material-icons,
  .material-symbols-outlined,
  .material-symbols-rounded,
  .material-symbols-sharp,
  [data-testid="stIconMaterial"],
  [data-testid="stBaseButton-headerNoPadding"] span,
  [data-testid="stSidebarCollapsedControl"] span,
  [data-testid="collapsedControl"] span {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
    font-weight: 300 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    font-variation-settings: "FILL" 0, "wght" 300, "GRAD" 0, "opsz" 24;
  }

  [data-testid="stCaption"] {
    color: var(--era-muted) !important;
    letter-spacing: 0.01em;
  }

  [data-testid="stSidebar"] { background: transparent !important; }

  [data-testid="stSidebar"] > div:first-child {
    background: rgba(8,8,10,0.72) !important;
    backdrop-filter: blur(28px);
    -webkit-backdrop-filter: blur(28px);
    margin: 1.25rem 0.85rem !important;
    border-radius: var(--era-radius) !important;
    border: 1px solid var(--era-hair) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.12);
  }

  [data-testid="stSidebarContent"] {
    padding: 1.6rem 1.15rem 2rem !important;
  }

  [data-testid="stFileUploaderDropzone"] {
    background: var(--era-core) !important;
    border: 1px solid var(--era-hair) !important;
    border-radius: var(--era-radius-in) !important;
    min-height: 9.5rem !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.12);
    transition: transform 700ms var(--era-ease), opacity 700ms var(--era-ease);
  }

  [data-testid="stFileUploader"] {
    background: var(--era-shell);
    border: 1px solid var(--era-hair);
    border-radius: var(--era-radius);
    padding: 0.4rem;
  }

  [data-testid="stFileUploaderDropzone"]:hover { transform: scale(0.995); }

  [data-testid="stFileUploaderDropzone"] p,
  [data-testid="stFileUploaderDropzone"] small,
  [data-testid="stFileUploaderDropzone"] button {
    color: var(--era-muted) !important;
    font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif !important;
  }

  .stButton > button,
  .stDownloadButton > button,
  [data-testid="stBaseButton-primary"],
  [data-testid="stBaseButton-secondary"] {
    font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
    font-size: 0.72rem !important;
    border-radius: var(--era-chip) !important;
    padding: 0.85rem 1.5rem !important;
    border: 1px solid var(--era-hair) !important;
    background: linear-gradient(180deg, #141416, #0B0B0D) !important;
    color: var(--era-ink) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.16);
    transition: transform 700ms var(--era-ease), opacity 700ms var(--era-ease);
  }

  .stButton > button[kind="primary"],
  [data-testid="stBaseButton-primary"] {
    background: linear-gradient(180deg, #E8C47A, #C4923A) !important;
    color: #14110C !important;
    border-color: transparent !important;
  }

  .stButton > button:hover,
  .stDownloadButton > button:hover { transform: scale(1.015); }

  .stButton > button:active,
  .stDownloadButton > button:active { transform: scale(0.98); }

  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.4rem;
    background: var(--era-shell);
    border: 1px solid var(--era-hair);
    border-radius: var(--era-chip);
    padding: 0.35rem;
  }

  [data-testid="stTabs"] button {
    font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif !important;
    border-radius: 0.5rem !important;
    color: var(--era-muted) !important;
  }

  [data-testid="stTabs"] button[aria-selected="true"] {
    background: #141416 !important;
    color: var(--era-ink) !important;
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.12);
  }

  [data-testid="stDataFrame"],
  [data-testid="stSelectbox"] > div {
    border-radius: 1.15rem !important;
    overflow: hidden;
  }

  div[data-baseweb="select"] > div {
    background: var(--era-core) !important;
    border: 1px solid var(--era-hair) !important;
    border-radius: 1.15rem !important;
  }

  [data-testid="stTextInput"] input,
  [data-testid="stNumberInput"] input {
    background: var(--era-core) !important;
    color: var(--era-ink) !important;
    border-radius: 1.15rem !important;
  }

  [data-testid="stExpander"] {
    background: var(--era-shell) !important;
    border: 1px solid var(--era-hair) !important;
    border-radius: var(--era-chip) !important;
    overflow: hidden;
  }

  [data-testid="stCheckbox"] label,
  [data-testid="stRadio"] label {
    color: var(--era-ink) !important;
  }

  [data-testid="stProgress"] > div > div {
    background: rgba(255,255,255,0.08) !important;
    border-radius: var(--era-chip) !important;
  }

  [data-testid="stProgress"] [data-testid="stProgressBar"] {
    background: var(--era-teal) !important;
  }

  [data-testid="stAlertContainer"] {
    background: var(--era-core) !important;
    color: var(--era-ink) !important;
    border: 1px solid var(--era-hair) !important;
    border-radius: 1.25rem !important;
  }

  .era-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    border-radius: 0.45rem;
    padding: 0.28rem 0.72rem;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--era-teal);
    background: rgba(228,179,99,0.10);
    border: 1px solid rgba(228,179,99,0.22);
    margin-bottom: 1.1rem;
  }

  .era-hero {
    display: grid;
    grid-template-columns: 1.35fr 0.85fr;
    gap: 2.4rem;
    align-items: end;
    margin: 0 0 3.5rem;
    animation: era-enter 900ms var(--era-ease) both;
  }

  @media (max-width: 768px) {
    .era-hero {
      grid-template-columns: 1fr;
      gap: 1.4rem;
    }
  }

  .era-hero h1 {
    font-size: clamp(2.6rem, 6vw, 4.6rem) !important;
    line-height: 0.92 !important;
    margin: 0 0 1rem !important;
  }

  .era-lede {
    font-size: 1.05rem;
    line-height: 1.65;
    color: var(--era-muted);
    max-width: 36rem;
  }

  .era-hero-aside {
    color: var(--era-muted);
    font-size: 0.92rem;
    line-height: 1.7;
    padding-bottom: 0.35rem;
  }

  .era-hero-aside strong { color: var(--era-ink); font-weight: 600; }

  .era-section {
    margin: 3.2rem 0 1.4rem;
    animation: era-enter 900ms var(--era-ease) both;
  }

  .era-section h2 {
    font-size: clamp(1.6rem, 3vw, 2.15rem) !important;
    margin: 0 0 0.45rem !important;
  }

  .era-shell {
    background: var(--era-shell);
    border: 1px solid var(--era-hair);
    border-radius: var(--era-radius);
    padding: 0.4rem;
  }

  .era-core {
    background: var(--era-core);
    border-radius: var(--era-radius-in);
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.14);
    padding: 1.35rem 1.45rem;
  }

  .era-bento {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 0.85rem;
    margin: 0.4rem 0 1.6rem;
  }

  .era-tile { grid-column: span 3; }
  .era-tile-lg { grid-column: span 6; }
  .era-tile-xl { grid-column: span 8; }
  .era-tile-sm { grid-column: span 4; }

  @media (max-width: 768px) {
    .era-bento { grid-template-columns: 1fr; }
    .era-tile, .era-tile-lg, .era-tile-xl, .era-tile-sm { grid-column: span 1; }
  }

  .era-kicker {
    font-size: 10px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--era-violet);
    margin-bottom: 0.55rem;
  }

  .era-value {
    font-family: "Syne", sans-serif;
    font-size: 2.05rem;
    font-weight: 700;
    letter-spacing: -0.04em;
    line-height: 1;
  }

  .era-value-xl {
    font-family: "Syne", sans-serif;
    font-size: clamp(3.2rem, 7vw, 4.8rem);
    font-weight: 800;
    letter-spacing: -0.06em;
    line-height: 0.9;
  }

  .era-track {
    margin-top: 1.1rem;
    height: 0.35rem;
    border-radius: var(--era-chip);
    background: rgba(255,255,255,0.08);
    overflow: hidden;
  }

  .era-fill {
    height: 100%;
    border-radius: var(--era-chip);
    background: linear-gradient(90deg, var(--era-teal), var(--era-violet));
    transform-origin: left center;
    animation: era-fill 1100ms var(--era-ease) both;
  }

  .era-insight-wrap {
    margin: 0.65rem 0;
    animation: era-enter 900ms var(--era-ease) both;
  }

  .era-insight {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.9rem;
    align-items: start;
  }

  .era-index {
    font-family: "Syne", sans-serif;
    font-size: 0.85rem;
    color: var(--era-teal);
    min-width: 1.8rem;
    padding-top: 0.15rem;
  }

  .era-insight p {
    margin: 0;
    font-size: 1.02rem;
    line-height: 1.55;
    color: var(--era-ink);
  }

  .era-cta {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
    border-radius: var(--era-chip);
    padding: 0.45rem 0.45rem 0.45rem 1.05rem;
    background: linear-gradient(180deg, #E8C47A, #C4923A);
    color: #14110C !important;
    text-decoration: none !important;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    transition: transform 700ms var(--era-ease);
  }

  .era-cta:hover { transform: scale(1.02); }
  .era-cta:active { transform: scale(0.98); }

  .era-cta-icon {
    width: 2rem;
    height: 2rem;
    border-radius: 0.5rem;
    background: rgba(20,17,12,0.12);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    transition: transform 700ms var(--era-ease);
  }

  .era-cta:hover .era-cta-icon {
    transform: translateX(3px) translateY(-1px) scale(1.05);
  }

  .era-side-title {
    font-family: "Syne", sans-serif;
    font-size: 1.35rem;
    letter-spacing: -0.04em;
    margin: 0 0 1rem;
  }

  .era-steps {
    list-style: none;
    padding: 0;
    margin: 0 0 1.6rem;
  }

  .era-steps li {
    display: grid;
    grid-template-columns: 1.6rem 1fr;
    gap: 0.55rem;
    margin: 0 0 0.85rem;
    color: var(--era-muted);
    font-size: 0.9rem;
    line-height: 1.45;
  }

  .era-steps b { color: var(--era-teal); font-family: "Syne", sans-serif; font-weight: 600; }

  .era-sev {
    display: inline-flex;
    align-items: center;
    border-radius: 0.4rem;
    padding: 0.12rem 0.45rem;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }

  .era-sev-high {
    color: #F3C1A0;
    background: rgba(243,193,160,0.12);
    border: 1px solid rgba(243,193,160,0.28);
  }

  .era-sev-medium {
    color: var(--era-teal);
    background: rgba(228,179,99,0.10);
    border: 1px solid rgba(228,179,99,0.22);
  }

  .era-sev-low {
    color: var(--era-muted);
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--era-hair);
  }

  .era-finding-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-bottom: 0.65rem;
    align-items: center;
  }

  @keyframes era-enter {
    from { opacity: 0; transform: translateY(2.4rem); }
    to { opacity: 1; transform: translateY(0); }
  }

  @keyframes era-fill {
    from { transform: scaleX(0); }
    to { transform: scaleX(1); }
  }

  footer { visibility: hidden; }
</style>
"""


def inject_theme() -> None:
    st.markdown(FONTS + CSS, unsafe_allow_html=True)


def section_header(eyebrow: str, title: str, lede: str = "") -> None:
    lede_html = f'<p class="era-lede">{escape(lede)}</p>' if lede else ""
    st.markdown(
        f"""
        <div class="era-section">
          <div class="era-eyebrow">{escape(eyebrow)}</div>
          <h2>{escape(title)}</h2>
          {lede_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def hero() -> None:
    st.markdown(
        """
        <div class="era-hero">
          <div>
            <div class="era-eyebrow">Quality inspector · no silent fixes</div>
            <h1>Find what the<br>spreadsheet hides.</h1>
            <p class="era-lede">
              Upload messy files. We diagnose missingness, duplicates, dates,
              and near-matches you would never catch by eye — then score the
              damage before a single cell is changed.
            </p>
          </div>
          <div class="era-hero-aside">
            <strong>What you leave with.</strong><br>
            A quality score, a reviewable plan, a cleaning certificate,
            and a cleaned table ready for the Excel Report Automator.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_chrome() -> None:
    st.markdown(
        f"""
        <div class="era-eyebrow">Protocol</div>
        <div class="era-side-title">How this works</div>
        <ol class="era-steps">
          <li><b>01</b><span>Drop .xlsx, .xls, or .csv — several files are fine</span></li>
          <li><b>02</b><span>Read the quality score first. Nothing has been cleaned yet</span></li>
          <li><b>03</b><span>Approve the plan — skip any step you do not want</span></li>
          <li><b>04</b><span>Apply, export the certificate, then brief the cleaned table</span></li>
        </ol>
        <p class="era-note">Need a polished briefing from the cleaned table?</p>
        <a class="era-cta" href="{EXCEL_REPORT_AUTOMATOR_URL}">
          Excel Report Automator
          <span class="era-cta-icon">↗</span>
        </a>
        """,
        unsafe_allow_html=True,
    )


def bento_tiles(specs: list[tuple[str, str, str, str]]) -> None:
    html = ['<div class="era-bento">']
    for cls, kicker, value, hint in specs:
        html.append(
            f"""
            <div class="{cls}">
              <div class="era-shell">
                <div class="era-core">
                  <div class="era-kicker">{escape(kicker)}</div>
                  <div class="era-value">{escape(value)}</div>
                  <p class="era-note" style="margin:0.65rem 0 0">{escape(hint)}</p>
                </div>
              </div>
            </div>
            """
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def quality_score_bento(
    score: int,
    caption: str,
    completeness: float,
    uniqueness: float,
    consistency: float,
    duplicates: int,
    *,
    after_score: int | None = None,
    after_completeness: float | None = None,
    after_uniqueness: float | None = None,
    after_consistency: float | None = None,
    after_duplicates: int | None = None,
) -> None:
    def _pair(before: float | int, after: float | int | None, as_int: bool = True) -> str:
        if after is None:
            return f"{int(before)}" if as_int else f"{before:.0f}"
        left = int(before) if as_int else f"{before:.0f}"
        right = int(after) if as_int else f"{after:.0f}"
        return f"{left}<span style=\"font-size:0.45em;letter-spacing:-0.02em;color:rgba(246,240,230,0.45)\"> → </span>{right}"

    headline = score if after_score is None else after_score
    width = max(0.0, min(100.0, float(headline)))
    kicker = "Your data quality score" if after_score is None else "Score before → after"
    big = (
        f'{score}<span style="font-size:0.38em;letter-spacing:-0.02em;color:rgba(243,241,236,0.45)">/100</span>'
        if after_score is None
        else (
            f'{score}<span style="font-size:0.38em;letter-spacing:-0.02em;color:rgba(243,241,236,0.45)"> → </span>'
            f'{after_score}<span style="font-size:0.38em;letter-spacing:-0.02em;color:rgba(243,241,236,0.45)">/100</span>'
        )
    )
    copies_hint = (
        "Duplicate rows in the raw file"
        if after_duplicates is None
        else f"Was {duplicates:,} exact copies"
    )
    st.markdown(
        f"""
        <div class="era-bento">
          <div class="era-tile-xl">
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">{escape(kicker)}</div>
                <div class="era-value-xl">{big}</div>
                <p class="era-note" style="margin:0.85rem 0 0">{escape(caption)}</p>
                <div class="era-track"><div class="era-fill" style="width:{width}%"></div></div>
              </div>
            </div>
          </div>
          <div class="era-tile-sm">
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Completeness</div>
                <div class="era-value">{_pair(completeness, after_completeness, as_int=True)}</div>
                <p class="era-note" style="margin:0.65rem 0 0">Weight ~40%</p>
              </div>
            </div>
          </div>
          <div class="era-tile">
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Uniqueness</div>
                <div class="era-value">{_pair(uniqueness, after_uniqueness, as_int=True)}</div>
                <p class="era-note" style="margin:0.65rem 0 0">Weight ~30%</p>
              </div>
            </div>
          </div>
          <div class="era-tile">
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Consistency</div>
                <div class="era-value">{_pair(consistency, after_consistency, as_int=True)}</div>
                <p class="era-note" style="margin:0.65rem 0 0">Weight ~30%</p>
              </div>
            </div>
          </div>
          <div class="era-tile-lg">
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Exact copies</div>
                <div class="era-value">{_pair(duplicates, after_duplicates, as_int=True)}</div>
                <p class="era-note" style="margin:0.65rem 0 0">{escape(copies_hint)}</p>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def note_cards(notes: list[str]) -> None:
    if not notes:
        return
    blocks = []
    for i, sentence in enumerate(notes, start=1):
        delay = min(i * 80, 480)
        blocks.append(
            f"""
            <div class="era-shell era-insight-wrap" style="animation-delay:{delay}ms">
              <div class="era-core era-insight">
                <div class="era-index">{i:02d}</div>
                <p>{escape(sentence)}</p>
              </div>
            </div>
            """
        )
    st.markdown("".join(blocks), unsafe_allow_html=True)


def handoff_card(url: str) -> None:
    st.markdown(
        f"""
        <div class="era-shell" style="margin:1.5rem 0 0.85rem">
          <div class="era-core">
            <div class="era-kicker">Next · briefing</div>
            <p class="era-lede" style="margin:0 0 0.95rem">
              This table is ready to brief. Download the handoff pack, then open
              Excel Report Automator and upload cleaned_data.xlsx.
            </p>
            <a class="era-cta" href="{escape(url)}" target="_blank" rel="noopener">
              Open Excel Report Automator
              <span class="era-cta-icon">↗</span>
            </a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def recipe_banner(line: str) -> None:
    if not line or line == "No steps selected":
        st.markdown(
            """
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Proposed plan</div>
                <p class="era-lede" style="margin:0">Nothing to apply — skip to Advanced if you still want a manual pass.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"""
        <div class="era-shell">
          <div class="era-core">
            <div class="era-kicker">Proposed plan</div>
            <p class="era-lede" style="margin:0.35rem 0 0">{escape(line)}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def finding_cards(findings) -> None:
    if not findings:
        st.markdown(
            """
            <div class="era-shell">
              <div class="era-core">
                <div class="era-kicker">Clean pass</div>
                <p class="era-lede" style="margin:0">No structural issues jumped out — still read the score breakdown.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    blocks = []
    for i, finding in enumerate(findings, start=1):
        delay = int(min(i * 70, 480))
        sev = _css_token(finding.severity, _SEV_TOKENS, "low")
        pillar = _css_token(finding.pillar, _PILLAR_TOKENS, "completeness")
        samples = ""
        if finding.samples:
            shown = " · ".join(escape(str(s)) for s in finding.samples[:4])
            samples = f'<p class="era-note" style="margin:0.65rem 0 0">Examples: {shown}</p>'
        column = (
            f'<span class="era-kicker" style="margin:0">{escape(finding.column)}</span>'
            if finding.column
            else ""
        )
        fix = (
            f'<p class="era-note" style="margin:0.45rem 0 0">Recommended: {escape(finding.recommended_fix)}</p>'
            if finding.recommended_fix
            else ""
        )
        blocks.append(
            f"""
            <div class="era-shell era-insight-wrap" style="animation-delay:{delay}ms">
              <div class="era-core era-insight">
                <div class="era-index">{i:02d}</div>
                <div>
                  <div class="era-finding-meta">
                    <span class="era-sev era-sev-{sev}">{escape(finding.severity)}</span>
                    <span class="era-kicker" style="margin:0">{escape(finding.pillar)}</span>
                    {column}
                  </div>
                  <p>{escape(finding.title)}</p>
                  <p class="era-note" style="margin:0.35rem 0 0">{escape(finding.detail)}</p>
                  {samples}
                  {fix}
                </div>
              </div>
            </div>
            """
        )
    st.markdown("".join(blocks), unsafe_allow_html=True)
