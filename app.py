import streamlit as st
import pandas as pd
import requests
import urllib.parse
from datetime import datetime
import time
import shutil
import tempfile
import os
from pathlib import Path
import anthropic
import ast 
from fpdf import FPDF 

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# --- CONFIGURATION ---
st.set_page_config(page_title="Lyreco Accessibility Monitor", layout="wide")

# Custom CSS for Lyreco Branding
st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #2D2E87;
        color: white;
        border-radius: 5px;
        border: none;
    }
    div.stButton > button:hover {
        background-color: #1a1b5e;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# Load secrets
try:
    GOOGLE_KEY = st.secrets["GOOGLE_KEY"]
    WAVE_KEY = st.secrets["WAVE_KEY"]
    CLAUDE_KEY = st.secrets["CLAUDE_KEY"]
except KeyError:
    st.error("⚠️ Missing API keys. Please add GOOGLE_KEY, WAVE_KEY, and CLAUDE_KEY to Streamlit Secrets.")
    st.stop()

client = anthropic.Anthropic(api_key=CLAUDE_KEY)

# --- DATA & MAPPING (Updated for WCAG 2.2 Links) ---
AXE_TO_WCAG = {
    "color-contrast": {"name": "SC 1.4.3 (Contrast Minimum)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html"},
    "image-alt": {"name": "SC 1.1.1 (Non-text Content)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html"},
    "label": {"name": "SC 3.3.2 (Labels or Instructions)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html"},
    "button-name": {"name": "SC 4.1.2 (Name, Role, Value)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"},
    "link-name": {"name": "SC 2.4.4 (Link Purpose)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html"},
    "html-has-lang": {"name": "SC 3.1.1 (Language of Page)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/language-of-page.html"},
    "document-title": {"name": "SC 2.4.2 (Page Titled)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/page-titled.html"},
    "frame-title": {"name": "SC 2.4.1 (Bypass Blocks)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/bypass-blocks.html"},
    "list": {"name": "SC 1.3.1 (Info and Relationships)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships.html"},
    "aria-allowed-attr": {"name": "SC 4.1.2 (Name, Role, Value)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"},
    "accesskeys": {"name": "SC 2.1.1 (Keyboard)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html"},
    "target-size": {"name": "SC 2.5.8 (Target Size Minimum)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html"},
    "focus-appearance": {"name": "SC 2.4.13 (Focus Appearance)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html"}
}

COUNTRIES = {
    "France": {
        "home": "https://shop.lyreco.fr/fr",
        "category": "https://shop.lyreco.fr/fr/list/001001/papier-et-enveloppes/papier-blanc",
        "product": "https://shop.lyreco.fr/fr/product/157.796/papier-blanc-a4-lyreco-multi-purpose-80-g-ramette-500-feuilles",
    },
    "UK": {
        "home": "https://shop.lyreco.co.uk/",
        "category": "https://shop.lyreco.co.uk/en/list/001001/paper-envelopes/white-office-paper",
        "product": "https://shop.lyreco.co.uk/en/product/159.543/lyreco-white-a4-80gsm-copier-paper-box-of-5-reams-5x500-sheets-of-paper",
    },
    "Italy": {
        "home": "https://shop.lyreco.it/it",
        "category": "https://shop.lyreco.it/it/list/001001/carte-e-buste/carta-bianca",
        "product": "https://shop.lyreco.it/it/product/4.016.865/carta-bianca-lyreco-a4-75-g-mq-risma-500-fogli",
    },
    "Poland": {
        "home": "https://shop.lyreco.pl/pl",
        "category": "https://shop.lyreco.pl/pl/list/001001/papier-i-koperty/papiery-biale-uniwersalne",
        "product": "https://shop.lyreco.pl/pl/product/159.543/papier-do-drukarki-lyreco-copy-a4-80-g-m-5-ryz-po-500-arkuszy",
    }
}
SSO_LOGIN = "https://welcome.lyreco.com/lyreco-customers/login"
PAGE_LABELS = {"home": "Home", "category": "Category", "product": "Product", "login": "Login (SSO)"}

# --- PDF GENERATOR ---
class PDFReport(FPDF):
    def header(self):
        try:
            pass
        except: pass
        self.set_font('Arial', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, 'Lyreco Accessibility Audit', 0, 1, 'R')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 16)
        self.set_text_color(45, 46, 135) 
        self.cell(0, 10, label, 0, 1, 'L')
        self.ln(4)

    def chapter_body(self, text):
        self.set_font('Arial', '', 11)
        self.set_text_color(0)
        self.multi_cell(0, 6, text)
        self.ln()

def generate_w3c_pdf(df):
    pdf = PDFReport()
    pdf.add_page()
    
    logo_path = "lyreco_logo.png"
    try:
        if not os.path.exists(logo_path):
            img_data = requests.get("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.png").content
            with open(logo_path, 'wb') as handler:
                handler.write(img_data)
        pdf.image(logo_path, x=10, y=8, w=40)
    except: pass
    
    pdf.ln(20)
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 15, "Accessibility Evaluation Report", 0, 1, 'L')
    
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 8, f"Date: {datetime.now().strftime('%B %d, %Y')}", 0, 1, 'L')
    pdf.cell(0, 8, f"Auditor: Lyreco Automated Agent", 0, 1, 'L')
    pdf.ln(10)

    pdf.chapter_title("1. Executive Summary")
    avg_score = df['Score'].mean()
    
    verdict = "Non-Compliant"
    if avg_score >= 90: verdict = "Excellent Compliance"
    elif avg_score >= 80: verdict = "Good Compliance"
    elif avg_score >= 60: verdict = "Partial Compliance"
    
    summary_text = (
        f"This report presents the results of an automated accessibility evaluation of the Lyreco e-commerce platform across selected markets. "
        f"The overall accessibility score is {avg_score:.1f}/100, categorized as '{verdict}'. "
        f"The evaluation highlights {int(df['Critical'].sum())} critical blockers and {int(df['Serious'].sum())} serious issues that require immediate attention to meet WCAG 2.2 AA standards."
    )
    pdf.chapter_body(summary_text)

    pdf.chapter_title("2. Scope of Evaluation")
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(40, 10, "Market", 1, 0, 'C', 1)
    pdf.cell(40, 10, "Page Type", 1, 0, 'C', 1)
    pdf.cell(110, 10, "URL (Truncated)", 1, 1, 'C', 1)
    
    pdf.set_font('Arial', '', 9)
    for _, row in df.iterrows():
        pdf.cell(40, 8, row['Country'], 1)
        pdf.cell(40, 8, row['Type'].capitalize(), 1)
        short_url = (row['URL'][:55] + '...') if len(row['URL']) > 55 else row['URL']
        pdf.cell(110, 8, short_url, 1, 1)
    pdf.ln(10)

    pdf.chapter_title("3. Detailed Findings")
    for _, row in df.iterrows():
        violations = row["Violations"]
        if isinstance(violations, str):
            try: violations = ast.literal_eval(violations)
            except: violations = []
        
        serious_violations = [v for v in violations if v.get('impact') in ['critical', 'serious']]
        
        if serious_violations:
            pdf.set_font('Arial', 'B', 11)
            pdf.set_text_color(45, 46, 135)
            pdf.cell(0, 10, f"{row['Country']} - {row['Type'].capitalize()} (Score: {row['Score']})", 0, 1)
            
            pdf.set_font('Arial', 'B', 9)
            pdf.set_text_color(0)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(30, 8, "Impact", 1, 0, 'C', 1)
            pdf.cell(60, 8, "Issue ID", 1, 0, 'C', 1)
            pdf.cell(100, 8, "Description", 1, 1, 'C', 1)
            
            pdf.set_font('Arial', '', 8)
            for v in serious_violations:
                impact = v.get('impact', 'minor').upper()
                pdf.set_text_color(200, 0, 0) if impact == 'CRITICAL' else pdf.set_text_color(0)
                pdf.cell(30, 8, impact, 1, 0, 'C')
                
                pdf.set_text_color(0)
                pdf.cell(60, 8, v['id'], 1, 0)
                pdf.cell(100, 8, v['help'], 1, 1)
            pdf.ln(5)
            
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_accessibility_statement_pdf(df):
    pdf = PDFReport()
    pdf.add_page()
    
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 15, "Accessibility Statement", 0, 1, 'L')
    pdf.ln(5)

    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 6, "Lyreco is committed to ensuring digital accessibility for people with disabilities. We are continually improving the user experience for everyone, and applying the relevant accessibility standards.")
    pdf.ln(5)

    pdf.chapter_title("Conformance Status")
    pdf.chapter_body("The Web Content Accessibility Guidelines (WCAG) defines requirements for designers and developers to improve accessibility for people with disabilities. It defines three levels of conformance: Level A, Level AA, and Level AAA. Based on recent automated audits, the Lyreco e-commerce platform is Partially Conformant with WCAG 2.2 level AA. Partially conformant means that some parts of the content do not fully conform to the accessibility standard.")
    
    pdf.chapter_title("Assessment Approach")
    pdf.chapter_body("Lyreco assessed the accessibility of the platform by the following approaches:")
    pdf.set_font('Arial', '', 11)
    pdf.cell(0, 6, "- Automated evaluation using Axe-core, WAVE, and Google Lighthouse.", 0, 1)
    pdf.cell(0, 6, "- AI-driven heuristic analysis based on WCAG 2.2 criteria.", 0, 1)
    pdf.ln(5)

    pdf.chapter_title("Identified Limitations")
    pdf.chapter_body("Despite our best efforts to ensure accessibility of the Lyreco platform, there may be some limitations. Below is a summary of known issues derived from our latest automated audit:")
    
    total_critical = int(df['Critical'].sum())
    total_serious = int(df['Serious'].sum())
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 6, f"Current Audit Metrics (Date: {datetime.now().strftime('%Y-%m-%d')}):", 0, 1)
    pdf.set_font('Arial', '', 11)
    pdf.cell(0, 6, f"- Critical Access Blockers: {total_critical}", 0, 1)
    pdf.cell(0, 6, f"- Serious Accessibility Issues: {total_serious}", 0, 1)
    pdf.ln(5)
    
    pdf.chapter_title("Feedback & Contact")
    pdf.chapter_body("We welcome your feedback on the accessibility of the Lyreco platform. Please let us know if you encounter accessibility barriers. This statement was generated automatically by the Lyreco Accessibility Agent.")

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- AUTHENTICATION SYSTEM ---
def check_password():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.image("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.svg", width=150)
            st.subheader("Lyreco WCAG Agent Login")
            user = st.text_input("User")
            pwd = st.text_input("Password", type="password")
            if st.button("Log in"):
                if user == "admin" and pwd == "admin2026":
                    st.session_state["logged_in"] = True
                    st.session_state["role"] = "admin"
                    st.rerun()
                elif user == "france" and pwd == "fr2026":
                    st.session_state["logged_in"] = True
                    st.session_state["role"] = "france"
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        return False
    return True

# --- AI ADVISOR ---
def get_ai_recommendation(violation_data, page_context):
    system_prompt = """
    You are a Senior Accessibility Specialist with IAAP certification (CPACC and WAS) and 12 years of experience.
    You specialize in inclusive design, WCAG 2.2 AA compliance, and testing with users with disabilities.
    You bridge the gap between technical standards and real-world barriers faced by users.
    """
    
    prompt = f"""
    Analyze this WCAG violation found on the Lyreco {page_context} page:
    Violation ID: {violation_data.get('id', 'unknown')}
    Impact: {violation_data.get('impact', 'unknown')}
    Description: {violation_data.get('help', '')}
    
    Provide an actionable accessibility remediation plan strictly using this Markdown format. Do not add introductory text.
    
    ### 👥 Affected User Groups
    (List which groups are impacted, e.g., screen reader users, keyboard-only users, low vision, and briefly explain why)
    
    ### 🚀 Quick Wins (< 1 day)
    (Immediate, simple HTML/CSS or content fixes)
    
    ### 🔧 Needs Development (1-5 days)
    (Complex logic, ARIA, or component-level changes needed)
    
    ### ⚙️ Needs Manual Testing
    (Specify what MUST be tested manually since automated tools cannot verify it, e.g., focus order, logical alt text)
    """
    
    try:
        # Używamy modelu Claude 3 Haiku - jest najszybszy i dostępny dla każdego poziomu API
        msg = client.messages.create(
            model="claude-3-haiku-20240307", 
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e: 
        return f"AI Advisor is currently unavailable. Error: {str(e)}"

# --- DASHBOARD ---
def display_results(df):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Average Accessibility Score", f"{df['Score'].mean():.1f}")
    m2.metric("Critical Blockers", int(df["Critical"].sum()))
    m3.metric("Serious Issues", int(df["Serious"].sum()))
    m4.metric("Markets Audited", len(df["Country"].unique()))

    st.subheader("Market Compliance Heatmap")
    pivot = df.pivot_table(index="Country", columns="Type", values="Score")
    st.dataframe(pivot.style.background_gradient(cmap="RdYlGn", vmin=0, vmax=100), use_container_width=True)

    st.subheader("❌ Detailed WCAG Violations (Prioritized)")
    violation_rows = []
    for _, row in df.iterrows():
        violations = row["Violations"]
        if isinstance(violations, str):
            try: violations = ast.literal_eval(violations)
            except: violations = []
            
        for v in violations:
            wcag_info = AXE_TO_WCAG.get(v["id"], {"name": "General Accessibility", "url": "https://www.w3.org/WAI/WCAG22/quickref/"})
            violation_rows.append({
                "Country": row["Country"],
                "Page": row["Type"].capitalize(),
                "Impact": v.get("impact", "minor").capitalize(),
                "WCAG Reference": wcag_info["name"],
                "WCAG URL": wcag_info["url"],
                "Description": v["help"],
                "Element Count": len(v.get("nodes", []))
            })
    
    if violation_rows:
        v_df = pd.DataFrame(violation_rows)
        # Sort by severity to show Critical first
        impact_order = {"Critical": 0, "Serious": 1, "Moderate": 2, "Minor": 3}
        v_df["sort_idx"] = v_df["Impact"].map(impact_order).fillna(4)
        v_df = v_df.sort_values(by=["sort_idx", "Country"]).drop(columns=["sort_idx"])
        
        st.dataframe(
            v_df, 
            column_config={
                "Impact": st.column_config.TextColumn("Impact", help="Severity of the issue"),
                "WCAG URL": st.column_config.LinkColumn("W3C Documentation", display_text="Open W3C Guideline"),
                "Element Count": st.column_config.NumberColumn("Occurrences")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("No violations found! 🎉")

    crit_df = df[df["Screenshot"] != ""]
    if not crit_df.empty:
        st.subheader("🖼️ Visual Proof (Critical Issues)")
        cols = st.columns(3)
        for i, (_, row) in enumerate(crit_df.iterrows()):
            with cols[i % 3]: st.image(row["Screenshot"], caption=f"{row['Country']} - {row['Type'].capitalize()}")

    st.subheader("🧠 AI Accessibility Advisor (Remediation Plan)")
    st.info("⚠️ **Note:** Automated tools detect ~30-40% of issues (mostly code-based). Areas marked with ⚙️ require manual verification by an auditor.")
    
    for _, row in df.iterrows():
        violations = row["Violations"]
        if isinstance(violations, str):
            try: violations = ast.literal_eval(violations)
            except: violations = []

        if violations:
            # Sort violations within the AI loop to prioritize critical ones
            sorted_violations = sorted(violations, key=lambda x: {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}.get(x.get("impact"), 4))
            
            with st.expander(f"Strategy: {row['Country']} - {row['Type'].capitalize()} (Top Issue)"):
                # Only analyzing the top highest severity issue to save tokens/time
                top_v = sorted_violations[0] 
                st.write(f"**Top Issue Detected:** {top_v['help']} (Severity: {top_v.get('impact', 'unknown').upper()})")
                st.markdown(get_ai_recommendation(top_v, row['Type']))

# --- MAIN ---
if check_password():
    with st.sidebar:
        st.image("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.svg", width=180)
        st.write(f"Logged as: **{st.session_state['role'].upper()}**")
        
        if "last_res" in st.session_state:
            st.divider()
            
            # 1. CSV Download
            csv = st.session_state["last_res"].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Data (CSV)",
                data=csv,
                file_name=f"lyreco_audit_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv',
                use_container_width=True
            )
            
            # 2. Audit Report PDF Download
            try:
                report_pdf_bytes = generate_w3c_pdf(st.session_state["last_res"])
                st.download_button(
                    label="📄 Download Audit Report (PDF)",
                    data=report_pdf_bytes,
                    file_name=f"Lyreco_Audit_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime='application/pdf',
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Report PDF Gen Error: {e}")

            # 3. Accessibility Statement PDF Download
            try:
                statement_pdf_bytes = generate_accessibility_statement_pdf(st.session_state["last_res"])
                st.download_button(
                    label="📜 Download Accessibility Statement",
                    data=statement_pdf_bytes,
                    file_name=f"Lyreco_Accessibility_Statement_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime='application/pdf',
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Statement PDF Gen Error: {e}")
            
        if st.button("Logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()
      
    tab1, tab2 = st.tabs(["🚀 New Audit", "📂 History"])
    
    with tab1:
        c1, c2 = st.columns(2)
        options = list(COUNTRIES.keys()) if st.session_state["role"] == "admin" else ["France"]
        sel_countries = c1.multiselect("Select Markets", options, default=options)
        sel_types = c2.multiselect("Select Pages", ["home", "category", "product", "login"], default=["home", "product"])

        if st.button("Run Audit", type="primary"):
            results = []
            for c in sel_countries:
                for t in sel_types:
                    st.write(f"Auditing {c} - {t.capitalize()}...")
                    results.append(perform_full_audit(COUNTRIES[c].get(t, SSO_LOGIN), t, c))
            st.session_state["last_res"] = pd.DataFrame(results)
            st.rerun()

        if "last_res" in st.session_state:
            display_results(st.session_state["last_res"])

    with tab2:
        up = st.file_uploader("Upload Previous Audit CSV")
        if up: 
            df = pd.read_csv(up)
            st.session_state["last_res"] = df
            display_results(df)

with st.expander("📊 How We Calculate Accessibility Score"):
    st.markdown(
        """
        ### Lyreco Accessibility Score (0-100)

        **Algorithm (v8.0):**

        **🔍 Google Lighthouse (40%)**
        - Tests 40+ accessibility rules including ARIA, semantics, and keyboard navigation.

        **🌊 WAVE by WebAIM (30%)**
        - Detects critical errors (missing alt text, broken forms) and color contrast failures.
        - Penalties: 1.2 points per error, 0.5 per contrast issue.

        **⚡ Axe-core (30%)**
        - Deep WCAG 2.2 compliance testing.
        - Heavy penalties: Critical violation = -10 points, Serious = -5 points.

        **📈 Score Ranges:**
        - 🟢🟢 95-100: Excellent Compliance
        - 🟢 90-95: Good Compliance
        - 🟡🟢 80-90: Fair Compliance
        - 🟡 60-80: Needs Improvement
        - 🔴 <60: Critical Access Blockers Found

        ⚠️ *Automated tools catch ~30-40% of issues. Manual testing is required for full WCAG compliance.*
        """
    )

st.divider()
