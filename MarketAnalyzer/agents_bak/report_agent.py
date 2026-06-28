"""fpdf2-based PDF report generator — produces unified verdict PDFs.

Follows the same format as gen_report_hpq.py / gen_report_igv.py
but is fully generic: any ticker, any verdict, any strategy.
"""

import math
import os
from datetime import date, datetime
from typing import Optional

from fpdf import FPDF

from agents.market_data_agent import MarketDataAgent
from agents.deep_dive_agent import DeepDiveAgent

FONT_DIR = '/usr/share/fonts/TTF/'
FONT = FONT_DIR + 'DejaVuSans.ttf'
FONT_B = FONT_DIR + 'DejaVuSans-Bold.ttf'
FONT_O = FONT_DIR + 'DejaVuSans-Oblique.ttf'
FONT_M = FONT_DIR + 'DejaVuSansMono.ttf'
FONT_MB = FONT_DIR + 'DejaVuSansMono-Bold.ttf'


class ReportPDF(FPDF):
    """Custom PDF class with DejaVu fonts, header, and footer."""

    def __init__(self):
        super().__init__()
        self.add_font('DejaVu', '', FONT)
        self.add_font('DejaVu', 'B', FONT_B)
        self.add_font('DejaVu', 'I', FONT_O)
        self.add_font('DejaVuMono', '', FONT_M)
        self.add_font('DejaVuMono', 'B', FONT_MB)

    def header(self):
        self.set_font('DejaVu', 'B', 9)
        self.set_text_color(120)
        self.cell(0, 6, 'MarketAnalyzer Report  |  Unified Verdict', align='L')
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', 'I', 8)
        self.set_text_color(150)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', align='C')


class ReportAgent:
    """Generates structural analysis PDF reports."""

    VERDICT_COLORS = {
        'LONG-TERM INVESTMENT': (25, 120, 60),
        'SHORT-TERM SPECULATION': (200, 130, 20),
        'AVOID': (180, 40, 40),
    }

    def __init__(self):
        self.mda = MarketDataAgent()
        self.dda = DeepDiveAgent()

    def generate_verdict_report(self, ticker: str, output_dir: str = 'reports') -> str:
        """Generate a full unified verdict PDF for any ticker."""
        result = self.dda.analyze(ticker)
        if 'error' in result:
            raise ValueError(f"Cannot generate report: {result['error']}")

        info = self.mda.get_info(ticker)
        hist = self.mda.get_history(ticker, '1y')

        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M')
        path = os.path.join(output_dir, f'{ticker}_verdict_{ts}.pdf')

        pdf = ReportPDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        self._cover_section(pdf, result, info)
        self._sinossi_section(pdf, result, hist)
        self._wyckoff_section(pdf, result)
        self._volume_profile_section(pdf, result)
        self._price_action_section(pdf, result)
        self._sentiment_section(pdf, result)
        self._fundamentals_section(pdf, result)
        self._scoring_section(pdf, result)

        pdf.output(path)
        return path

    def generate_strategy_report(self, ticker: str, strategy_name: str,
                                  strikes: list[float], premiums: list[float],
                                  sides: list[str], expiry: str,
                                  output_dir: str = 'reports') -> str:
        """Generate a strategy-focused PDF (e.g. Synthetic Long 2:1)."""
        result = self.dda.analyze(ticker)
        info = self.mda.get_info(ticker)

        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M')
        path = os.path.join(output_dir, f'{ticker}_{strategy_name}_{ts}.pdf')

        pdf = ReportPDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        self._cover_section(pdf, result, info, subtitle=strategy_name)
        self._strategy_table(pdf, strikes, premiums, sides, expiry)
        self._wyckoff_section(pdf, result)
        self._volume_profile_section(pdf, result)
        self._price_action_section(pdf, result)
        self._scoring_section(pdf, result)

        pdf.output(path)
        return path

    # ── PDF sections ─────────────────────────────────────────

    @staticmethod
    def _color_for_verdict(verdict: str) -> tuple:
        for k, v in ReportAgent.VERDICT_COLORS.items():
            if k in verdict.upper():
                return v
        return (60, 60, 60)

    def _cover_section(self, pdf: ReportPDF, result: dict, info: dict,
                       subtitle: Optional[str] = None):
        verdict = result.get('verdict', 'N/A')
        vcolor = self._color_for_verdict(verdict)

        pdf.set_font('DejaVu', 'B', 28)
        pdf.set_text_color(*vcolor)
        pdf.cell(0, 14, f'{result["ticker"]} — {verdict}', align='L')
        pdf.ln(12)
        pdf.set_font('DejaVu', '', 14)
        pdf.set_text_color(60)
        title = subtitle or f'Analisi Completa — {info.get("longName", info.get("shortName", result["ticker"]))}'
        pdf.cell(0, 8, title, align='L')
        pdf.ln(8)
        pdf.set_font('DejaVu', '', 10)
        pdf.cell(0, 6, f'Report generato il {date.today().isoformat()} | Score: {result["final_score"]}/100', align='L')
        pdf.ln(16)

    def _sinossi_section(self, pdf: ReportPDF, result: dict, hist):
        vcolor = self._color_for_verdict(result['verdict'])
        pdf.set_fill_color(*vcolor)
        pdf.set_text_color(255)
        pdf.set_font('DejaVu', 'B', 13)
        pdf.cell(0, 10, '  SINOSSI', fill=True, align='L')
        pdf.ln(12)
        pdf.set_text_color(30)

        rsi = 50
        vol = 0
        if hist is not None and not hist.empty:
            delta = hist['Close'].diff()
            up = delta.clip(lower=0)
            down = -delta.clip(upper=0)
            ma_up = up.ewm(com=13).mean()
            ma_down = down.ewm(com=13).mean()
            rs = ma_up / ma_down.replace(0, float('inf'))
            rsi = (100 - 100 / (1 + rs)).iloc[-1]
            vol = float(hist['Close'].pct_change().std() * math.sqrt(252) * 100)

        infos = [
            ('Ticker', f'{result["ticker"]} ({result.get("name", "")})'),
            ('Prezzo', f'$ {result["price"]:.2f}'),
            ('Score', f'{result["final_score"]}/100 — {result["verdict"]}'),
            ('Direzione', result.get('direction', 'N/A')),
            ('RSI(14)', f'{rsi:.1f}'),
            ('Vol. Annua', f'{vol:.1f}%'),
        ]
        for label, val in infos:
            pdf.set_font('DejaVuMono', '', 10)
            pdf.cell(42, 6, f'  {label}')
            pdf.set_font('DejaVuMono', 'B', 10)
            pdf.cell(0, 6, str(val))
            pdf.ln(5)

    def _strategy_table(self, pdf: ReportPDF, strikes: list[float],
                        premiums: list[float], sides: list[str], expiry: str):
        pdf.ln(4)
        pdf.set_fill_color(230, 237, 247)
        pdf.set_text_color(30)
        pdf.set_font('DejaVu', 'B', 13)
        pdf.cell(0, 10, '  STRUTTURA', fill=True, align='L')
        pdf.ln(14)
        pdf.set_font('DejaVuMono', '', 10)

        cols = [('Gamba', 28), ('Qty', 12), ('Strike', 20), ('Prezzo', 22), ('Incasso/Costo', 32)]
        for c in cols:
            pdf.cell(c[1], 8, c[0], border=1, align='C')
        pdf.ln()

        for strike, premium, side in zip(strikes, premiums, sides):
            qty = '2x' if side.startswith('sell p') else '1x'
            incasso = f'+$ {premium * (2 if qty == "2x" else 1) * 100:,.0f}' if side.startswith('sell') else f'-$ {premium * 100:,.0f}'
            pdf.set_font('DejaVuMono', '', 10)
            for i, val in enumerate([side, qty, f'${strike:.2f}', f'${premium:.2f}', incasso]):
                w = cols[i][1] if i < 4 else 32
                pdf.cell(w, 8, val, border=1, align='C')
            pdf.ln()

        net_premium = sum(p * (-1 if 'sell' in s else 1) for p, s in zip(premiums, sides))
        net_label = f'${abs(net_premium):.2f} CREDITO' if net_premium < 0 else f'${abs(net_premium):.2f} DEBITO'
        pdf.set_font('DejaVuMono', 'B', 10)
        for i, val in enumerate(['NETTO', '', '', '', net_label]):
            w = cols[i][1] if i < 4 else 32
            pdf.cell(w, 8, val, border=1, align='C')
        pdf.ln(8)
        pdf.set_font('DejaVu', 'I', 9)
        pdf.set_text_color(100)
        pdf.multi_cell(0, 5, f'Scadenza: {expiry} | {net_label} alla apertura.')

    def _wyckoff_section(self, pdf: ReportPDF, result: dict):
        pdf.add_page()
        wy = result.get('wyckoff', {})
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(0, 12, '1. Wyckoff Phase', align='L')
        pdf.ln(14)
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(30)
        pdf.cell(0, 7, f"Phase: {wy.get('phase', 'N/A')}")
        pdf.ln(7)
        pdf.cell(0, 7, f"Score: {wy.get('score', 'N/A')}/100")
        pdf.ln(7)
        pdf.set_font('DejaVuMono', '', 10)
        details = [
            f"Range position: {wy.get('range_pct', 'N/A')}%",
            f"Spring: {'Yes' if wy.get('spring') else 'No'}",
            f"Upthrust: {'Yes' if wy.get('upthrust') else 'No'}",
            f"SOS/SOW: {wy.get('sos', 0)}/{wy.get('sow', 0)}",
            f"HH/HL: {'Yes' if wy.get('hh_hl') else 'No'}",
            f"Volume ratio 20v60: {wy.get('vol_ratio_20v60', 'N/A')}%",
        ]
        for d in details:
            pdf.cell(0, 6, f'  {d}')
            pdf.ln(5)

    def _volume_profile_section(self, pdf: ReportPDF, result: dict):
        vp = result.get('volume_profile', {})
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(0, 12, '2. Volume Profile', align='L')
        pdf.ln(14)
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(30)
        details = [
            f"Shape: {vp.get('shape', 'N/A')}",
            f"POC: ${vp.get('poc', 'N/A')}",
            f"VA: ${vp.get('val', 'N/A')} - ${vp.get('vah', 'N/A')}",
            f"Price vs POC: {vp.get('price_vs_poc', 'N/A')}",
            f"Price vs VA: {vp.get('price_vs_va', 'N/A')}",
            f"Score: {vp.get('score', 'N/A')}/100",
        ]
        for d in details:
            pdf.cell(0, 7, d)
            pdf.ln(7)

    def _price_action_section(self, pdf: ReportPDF, result: dict):
        pa = result.get('price_action', {})
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(0, 12, '3. Price Action', align='L')
        pdf.ln(14)
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(30)
        details = [
            f"Verdict: {pa.get('verdict', 'N/A')}",
            f"Score: {pa.get('score', 'N/A')}/100",
            f"VPA Bull/Bear/Rev: {pa.get('vpa_bull', 0)}/{pa.get('vpa_bear', 0)}/{pa.get('vpa_rev', 0)}",
            f"Effort/Result: {pa.get('er', 0)}",
            f"EMA25: {'Rising' if pa.get('ema25_up') else 'Flat/Falling'}",
            f"Buildup: {'Yes' if pa.get('buildup') else 'No'}",
            f"Weis Score: {pa.get('weis', 0)}",
        ]
        for d in details:
            pdf.cell(0, 7, d)
            pdf.ln(7)

    def _sentiment_section(self, pdf: ReportPDF, result: dict):
        sent = result.get('sentiment', {})
        tatc = result.get('tatc', {})
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(0, 12, '4. Sentiment & Crowd', align='L')
        pdf.ln(14)
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(30)
        pdf.cell(0, 7, f"Sentiment Score: {sent.get('score', 'N/A')}/100")
        pdf.ln(7)
        pdf.cell(0, 7, f"TATC Direction: {tatc.get('direction', 'N/A')} ({tatc.get('score', 0)})")
        pdf.ln(7)
        pdf.set_font('DejaVu', 'I', 10)
        if tatc.get('signals'):
            pdf.multi_cell(0, 6, '  Signals: ' + ' | '.join(tatc['signals'][:5]))
        pdf.ln(4)

    def _fundamentals_section(self, pdf: ReportPDF, result: dict):
        fund = result.get('fundamentals', {})
        pdf.set_font('DejaVu', 'B', 16)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(0, 12, '5. Fundamentals', align='L')
        pdf.ln(14)
        pdf.set_font('DejaVu', '', 11)
        pdf.set_text_color(30)
        details = [
            f"P/E: {fund.get('pe', 'N/A')}",
            f"Revenue Growth: {fund.get('rev_growth', 'N/A')}%",
            f"Institutional Ownership: {fund.get('inst_own', 'N/A')}%",
            f"Profit Margins: {fund.get('margins', 'N/A')}%",
            f"D/E: {fund.get('dte', 'N/A')}",
            f"Score: {fund.get('score', 'N/A')}/100",
        ]
        for d in details:
            pdf.cell(0, 7, d)
            pdf.ln(7)
        if fund.get('reasons'):
            pdf.set_font('DejaVu', 'I', 10)
            for r in fund['reasons']:
                pdf.cell(0, 6, f'  → {r}')
                pdf.ln(6)

    def _scoring_section(self, pdf: ReportPDF, result: dict):
        dims = result.get('dimensions', {})
        vcolor = self._color_for_verdict(result['verdict'])
        pdf.add_page()
        pdf.set_font('DejaVu', 'B', 18)
        pdf.set_text_color(*vcolor)
        pdf.cell(0, 12, f'VERDETTO: {result.get("verdict", "N/A")}', align='L')
        pdf.ln(14)

        pdf.set_font('DejaVuMono', '', 10)
        pdf.set_text_color(30)
        pdf.cell(0, 8, f'Score Finale: {result["final_score"]:.1f}/100')
        pdf.ln(8)
        pdf.cell(0, 8, f'Direzione: {result.get("direction", "N/A")}')
        pdf.ln(8)
        pdf.cell(0, 8, f'Azione: {result.get("action", "N/A")}')
        pdf.ln(12)

        pdf.set_font('DejaVu', 'B', 11)
        pdf.cell(0, 8, 'Dettaglio Dimensioni:')
        pdf.ln(10)
        pdf.set_font('DejaVuMono', '', 10)

        for name, (sc, wt) in dims.items():
            pdf.cell(0, 7, f'  {name:<20} {sc:3.0f}/100  x {wt:.2f}  =  {sc * wt:5.1f}')
            pdf.ln(7)
