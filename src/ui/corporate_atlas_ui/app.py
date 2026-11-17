"""Run: python -m streamlit run src/ui/corporate_atlas_ui/app.py --server.address 127.0.0.1"""
import html
import base64
import time
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import streamlit as st

from corporate_atlas_ui.api_client import AtlasClient, APIError
from corporate_atlas_ui.answer_display import readable_answer, answer_markdown
from corporate_atlas.settings import SETTINGS

BRAND_ICON = Path(__file__).resolve().parent / 'assets' / 'capgemini-icon.png'

st.set_page_config(page_title='Corporate Atlas | Company Insights', page_icon=str(BRAND_ICON), layout='wide',
                   initial_sidebar_state='collapsed', menu_items={'Get help': None, 'Report a Bug': None, 'About': None})
# Streamlit's hosting shortcut is unrelated to this local workflow.
st.markdown('''<style>
/* Prefer Claude's typefaces when installed, with local fallbacks. */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stMarkdownContainer"], textarea {
    font-family:"Anthropic Serif", "anthropic-serif", Charter, Georgia, serif !important;
}
[data-testid="stAppViewContainer"] h1, [data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3, [data-testid="stAppViewContainer"] h4 {
    font-family:"Anthropic Serif", "anthropic-serif", Charter, Georgia, serif !important;
    font-weight:500;
}
button, input, label, [data-baseweb="select"], [data-testid="stCaptionContainer"] {
    font-family:"Anthropic Sans", "anthropic-sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif !important;
}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {line-height:1.75}
pre, code {font-family:"Anthropic Mono", "SFMono-Regular", Consolas, monospace !important}
/* Hide browser-injected Grammarly controls within the application. */
grammarly-desktop-integration, grammarly-extension,
grammarly-popups, [data-grammarly-shadow-root],
[data-grammarly-part] {display:none !important}
/* Hide Streamlit's app menu, hosting controls, and branding. */
#MainMenu, [data-testid="stMainMenu"],
[data-testid="stToolbar"], [data-testid="stToolbarActions"],
.stAppDeployButton, [data-testid="stAppDeployButton"],
footer, [data-testid="stFooter"] {display:none !important}
.workflow {display:flex;align-items:flex-start;margin:24px 0 32px}
.stage {flex:1;position:relative;text-align:center;color:#64748b;padding:0 8px}
.stage:after {content:"";position:absolute;height:3px;background:#cbd5e1;top:31px;left:calc(50% + 34px);width:calc(100% - 68px)}
.stage:last-child:after {display:none}
.stage.completed:after {background:#22c55e}
.circle {width:64px;height:64px;border-radius:50%;border:3px solid #cbd5e1;background:#f8fafc;color:#64748b;display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:24px;font-weight:700}
.stage strong {display:block;font-size:15px}
.stage small {display:block;margin-top:8px;line-height:1.5;font-size:12px}
.running .circle {background:#fff7ed;border-color:#f97316;color:#c2410c;animation:pulse 1.3s infinite}
.running strong {color:#f97316}
.completed .circle {background:#f0fdf4;border-color:#16a34a;color:#15803d}
.failed .circle,.stopped .circle {background:#fef2f2;border-color:#dc2626;color:#dc2626}
@keyframes pulse {50% {box-shadow:0 0 0 8px #f9731626}}
@media(prefers-reduced-motion:reduce){.running .circle{animation:none}}
</style>''', unsafe_allow_html=True)


@st.cache_resource
def backend_client():
    return AtlasClient()


runner = backend_client()


def backend_snapshot():
    try:
        return runner.snapshot()
    except APIError as exc:
        st.error(str(exc))
        st.stop()


def preparation_running():
    current = backend_snapshot()
    return bool(current and current['action'] == 'prepare' and current['status'] in {'running', 'stopping'})


ui_locked = preparation_running()
st.session_state.preparation_ui_locked = ui_locked

if st.session_state.get('company_table') and 'Accession' not in st.session_state.company_table[0]:
    st.session_state.pop('company_table', None)


def start(action, **kwargs):
    try:
        job = runner.start({'action': action, **kwargs})
        if action == 'prepare':
            st.session_state.preparing_tickers = re.split(r'[\s,]+', kwargs['tickers'].strip().upper())
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
    else:
        st.rerun()


title_column, settings_column = st.columns([12, 1], vertical_alignment='center')
with title_column:
    icon_data = base64.b64encode(BRAND_ICON.read_bytes()).decode('ascii')
    st.markdown(f'''<div style="display:flex;align-items:center;gap:14px;margin:0 0 8px;">
        <img src="data:image/png;base64,{icon_data}" alt="Capgemini" style="width:44px;height:44px;object-fit:contain;flex-shrink:0;">
        <h1 style="margin:0;padding:0;line-height:1.2;font-size:clamp(1.7rem,4vw,2.75rem);">Corporate Atlas</h1>
        </div>''', unsafe_allow_html=True)
    st.caption('Insights on publicly traded companies · Grounded in SEC filings')
with settings_column:
    with st.popover('⚙️', help='Research settings', disabled=ui_locked):
        st.subheader('Settings')
        mode = st.selectbox('Answer using', ['hybrid', 'graph', 'vector'], disabled=ui_locked)
        top_k = st.number_input('Context items per source', 1, 50, 12, disabled=ui_locked)
        with st.expander('Preparation settings'):
            batch_size = st.number_input('Chunks per batch', 1, 100, 5, disabled=ui_locked)
            batch_delay = st.number_input('Pause between batches (seconds)', 0, 600, 0, disabled=ui_locked)

appearance = 'Dark'
text_size = 'Medium'

palette = ({'background': '#0e1117', 'surface': '#1b2130', 'text': '#f1f5f9', 'muted': '#b4c0d4', 'border': '#475569'}
           if appearance == 'Dark' else
           {'background': '#faf9f5', 'surface': '#f3f1e9', 'text': '#141413', 'muted': '#68665f', 'border': '#dedbd1'})
font_size = {'Small': 14, 'Medium': 16, 'Large': 19}[text_size]
st.markdown(f"""<style>
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {{background:{palette['background']}; color:{palette['text']}}}
[data-testid="stAppViewContainer"] h1, [data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3, [data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] label {{color:{palette['text']}}}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {{font-size:{font_size}px}}
[data-testid="stCaptionContainer"] {{color:{palette['muted']}}}
[data-testid="stExpander"], [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {{border-color:{palette['border']}}}
[data-testid="stExpander"] summary {{color:{palette['text']}}}
[data-baseweb="popover"], [data-baseweb="popover"] [data-testid="stVerticalBlock"] {{background:{palette['surface']}; color:{palette['text']}}}
[data-baseweb="popover"] label, [data-baseweb="popover"] h3 {{color:{palette['text']}}}
/* Popovers are rendered outside the page container; theme their nested controls explicitly. */
[data-testid="stPopoverBody"], [data-baseweb="popover"] {{background:{palette['surface']} !important; color:{palette['text']} !important; color-scheme:{'dark' if appearance == 'Dark' else 'light'}}}
[data-testid="stPopoverBody"] [data-testid="stExpander"],
[data-testid="stPopoverBody"] details,
[data-baseweb="popover"] [data-testid="stExpander"],
[data-baseweb="popover"] details {{background:{palette['surface']} !important; border-color:{palette['border']} !important}}
[data-testid="stPopoverBody"] p, [data-testid="stPopoverBody"] label,
[data-testid="stPopoverBody"] summary, [data-testid="stPopoverBody"] summary svg,
[data-testid="stPopoverBody"] h3, [data-baseweb="popover"] p,
[data-baseweb="popover"] summary, [data-baseweb="popover"] summary svg {{color:{palette['text']} !important}}
[data-testid="stPopoverBody"] [data-baseweb="input"],
[data-testid="stPopoverBody"] input,
[data-testid="stPopoverBody"] [data-testid="stNumberInput"] button,
[data-baseweb="popover"] [data-baseweb="input"],
[data-baseweb="popover"] input,
[data-baseweb="popover"] [data-testid="stNumberInput"] button {{background:{palette['background']} !important; color:{palette['text']} !important}}

[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {{background:{palette['surface']}; color:{palette['text']}}}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {{color:{palette['muted']}}}
/* Explicit borders override Streamlit's default input outlines in both themes. */
[data-testid="stTextArea"] [data-baseweb="textarea"],
[data-testid="stTextInput"] [data-baseweb="input"] {{
    border:1px solid {('#64748b' if appearance == 'Dark' else '#d4d0c5')} !important;
    border-radius:10px !important;
    transition:border-color .15s ease, box-shadow .15s ease;
}}
[data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within,
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{
    border-color:{('#60a5fa' if appearance == 'Dark' else '#b65b3e')} !important;
    box-shadow:0 0 0 3px {('#60a5fa26' if appearance == 'Dark' else '#d9775726')} !important;
}}

[data-testid="stButton"] button[kind="secondary"], [data-testid="stPopover"] button {{background:{palette['surface']}; color:{palette['text']}; border-color:{palette['border']}}}
</style>""", unsafe_allow_html=True)


if appearance == 'Light':
    st.markdown('''<style>
    [data-testid="stApp"] {background:#faf9f5;color:#141413}
    [data-testid="stMarkdownContainer"] {color:#141413}
    [data-testid="stCaptionContainer"] p {color:#68665f}
    [data-testid="stForm"] {background:#fffefa;border:1px solid #e8e6dc;border-radius:14px}
    [data-testid="stTextArea"] [data-baseweb="textarea"],
    [data-testid="stTextInput"] [data-baseweb="input"],
    [data-testid="stTextArea"] textarea, [data-testid="stTextInput"] input {background:#fffefa !important;color:#141413 !important}
    [data-testid="stExpander"] {background:#faf9f5;border-color:#e8e6dc}
    [data-testid="stExpander"] summary:hover {background:#f0eee6;color:#141413}
    button[kind="primary"], [data-testid="stBaseButton-primary"] {background:#d97757 !important;border-color:#d97757 !important;color:#141413 !important}
    button[kind="primary"]:hover:not(:disabled) {background:#cc6b4b !important;border-color:#cc6b4b !important}
    button[kind="secondary"] {background:#f3f1e9 !important;border-color:#d4d0c5 !important;color:#141413 !important}
    button[kind="secondary"]:hover:not(:disabled) {background:#e8e6dc !important;border-color:#b0aea5 !important}
    button:disabled {opacity:.45}
    [data-testid="stMarkdownContainer"] a {color:#a34f35}
    [data-testid="stHorizontalBlock"] hr, hr {border-color:#e8e6dc}
    [data-testid="stPopoverBody"] {background:#faf9f5 !important;box-shadow:0 8px 30px #14141314}
    </style>''', unsafe_allow_html=True)


def workflow(job):
    if not job or job['action'] != 'prepare':
        return
    if job['status'] == 'completed':
        finished = job.get('finished_at', job.get('started', 0) + job.get('elapsed', 0))
        if time.time() - finished < 10:
            symbols = job.get('tickers') or st.session_state.get('preparing_tickers', [])
            if symbols:
                key = 'company_labels_' + job['id']
                if key not in st.session_state:
                    st.session_state[key] = ', '.join(runner.company_label(t) for t in symbols)
                st.success(f"Information for {st.session_state[key]} is ready. Ask a question above.")
        return
    st.subheader('Preparing your information')
    if job['status'] in {'running', 'stopping'}:
        active_step = next((name for name, step in job['steps'].items() if step['status'] == 'running'), 'download')
        processing_label = {'download': 'Fetching company filings…', 'graph': 'Building knowledge graphs…', 'vector': 'Preparing searchable filing data…'}[active_step]
        st.status(processing_label if job['status'] == 'running' else 'Stopping…', state='running', expanded=False)
    labels = {'download': 'Download filings', 'graph': 'Build knowledge graphs', 'vector': 'Build vector store'}
    cards = []
    for number, (name, label) in enumerate(labels.items(), 1):
        step = job['steps'][name]
        status = step['status']
        symbol = '✓' if status == 'completed' else '!' if status in {'failed', 'stopped'} else str(number)
        cards.append(f'<div class="stage {status}"><div class="circle">{symbol}</div><strong>{label}</strong>'
                     f'<small>{html.escape(step["message"] or status.capitalize())}</small></div>')
    st.markdown('<div class="workflow">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
    completed = sum(step['status'] == 'completed' for step in job['steps'].values())
    st.progress(completed / 3, text=f'{completed} of 3 stages complete · {job["elapsed"] // 60}m {job["elapsed"] % 60:02}s')
    if 'We already have' in job['output']:
        st.info(next(line for line in job['output'].splitlines() if line.startswith('We already have')))
    if job['status'] in {'failed', 'stopped'}:
        st.warning('Preparation ' + job['status'] + '. New downloads are cleaned up if preparation cannot finish. Click Download to try again.')
    with st.expander('Preparation details', expanded=job['status'] == 'failed'):
        st.code(job['output'] or 'Starting…', language='text')


st.subheader('What would you like to know?')
st.caption('Ask across available companies, or mention a company or ticker to focus your question.')
with st.form('question_form'):
    question = st.text_area(
        'Your question',
        placeholder='What are the key risks facing Apple? How do revenue trends compare across companies?',
        max_chars=SETTINGS.query.max_question_chars,
        disabled=ui_locked,
    )
    ask = st.form_submit_button('Explore insights', type='primary', disabled=ui_locked)
if ask:
    start('query', question=question, mode=mode, top_k=top_k)


@st.fragment(run_every='1s')
def answer_panel():
    job = backend_snapshot()
    if job and job['action'] == 'query':
        output = job['output'].strip()
        if job['status'] in {'running', 'stopping'}:
            st.status('Fetching filing insights…' if job['status'] == 'running' else 'Stopping…',
                      state='running', expanded=False)
            if st.button('Stop task', disabled=job['status'] == 'stopping'):
                runner.stop(job['id'])
                st.rerun(scope='fragment')
        elif job['status'] == 'completed':
            if job['action'] == 'query':
                with st.container(border=True):
                    st.markdown('#### Answer')
                    st.markdown(answer_markdown(output) or 'The model returned no answer.')
                st.download_button('Save answer', readable_answer(output), file_name='sec_answer.txt')
            else:
                st.text(output)
        else:
            st.error('Task ' + job['status'] + '. See details below.')
            st.code(output, language='text')
    try:
        state = runner.inventory()
    except APIError as exc:
        st.error(str(exc))
        return
    if not state['env_exists']:
        st.warning('Configure .env before preparing filings or asking questions.')


answer_panel()


@st.fragment(run_every='1s')
def preparation_panel():
    if preparation_running() != st.session_state.get('preparation_ui_locked', False):
        # Refresh the controls once on workflow completion, rather than every poll.
        st.rerun()
    job = backend_snapshot()
    busy = bool(job and job['status'] in {'running', 'stopping'})
    st.divider()
    with st.expander('Add a company to your research', expanded=bool(job and job['action'] == 'prepare' and busy)):
        st.caption('Enter a ticker to prepare its quarterly filings for your questions.')
        with st.form('prepare_form'):
            tickers = st.text_input('Company ticker', placeholder='e.g. AAPL or AAPL, WFC', key='company_ticker', disabled=busy)
            download = st.form_submit_button('Download', disabled=busy)
        if download:
            start('prepare', tickers=tickers, batch_size=batch_size, batch_delay=batch_delay)
    workflow(job)


preparation_panel()

with st.expander('Usage'):
    if st.button('View token usage', disabled=ui_locked):
        st.session_state.show_token_usage = True
    if st.session_state.get('show_token_usage'):
        try:
            usage_rows = runner.usage()
            if usage_rows:
                columns = ['Operation', 'Input tokens', 'Output tokens', 'Events', 'Estimated events']
                st.dataframe([dict(zip(columns, row)) for row in usage_rows],
                             hide_index=True, use_container_width=True)
            else:
                st.info('No token usage has been recorded yet.')
        except Exception as exc:
            st.error(f'Unable to read token usage: {exc}')

@st.cache_resource
def company_loader():
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix='company-list')


def load_companies():
    return runner.filings()


@st.fragment(run_every='1s')
def companies_panel():
    loaded = 'company_table' in st.session_state
    with st.expander('Available company information', expanded=loaded or 'company_load' in st.session_state):
        st.caption('View saved companies, downloaded quarters, and index availability.')
        deletion = backend_snapshot()
        deleting = bool(deletion and deletion['action'] == 'delete_filings' and deletion['status'] in {'running', 'stopping'})
        if deleting:
            st.status('Deleting selected fiscal-quarter downloads…', state='running', expanded=False)
        elif deletion and deletion['action'] == 'delete_filings':
            if deletion['status'] == 'completed':
                if st.session_state.get('handled_company_deletion') != deletion['id']:
                    st.session_state.handled_company_deletion = deletion['id']
                    st.session_state.pop('company_table', None)
                    st.session_state.company_load = company_loader().submit(load_companies)
                    st.session_state.company_loading_started = True
                finished_at = deletion.get('finished_at', deletion.get('started', 0) + deletion.get('elapsed', 0))
                remaining = 5 - (time.time() - finished_at)
                if remaining > 0:
                    message = html.escape(deletion['output'].strip()).replace('\n', '<br>')
                    # Preserve the original expiry across periodic fragment updates.
                    fade_delay = max(0.0, remaining - 0.7)
                    st.markdown(f'''<div role="status" style="padding:14px 18px;border-radius:10px;
                        background:#15803d20;border:1px solid #22c55e;color:inherit;
                        animation:delete-message-fade .7s ease {fade_delay:.2f}s forwards">{message}</div>
                        <style>@keyframes delete-message-fade {{to {{opacity:0;visibility:hidden}}}}</style>''',
                        unsafe_allow_html=True)
            elif deletion['status'] in {'failed', 'stopped'}:
                st.error('Deletion ' + deletion['status'] + '. Review details and refresh the company list.')
                st.code(deletion['output'], language='text')

        future = st.session_state.get('company_load')
        # Consume completed work before rendering the button so it is enabled again.
        first_loading_render = st.session_state.pop('company_loading_started', False)
        if future is not None and future.done() and not first_loading_render:
            try:
                st.session_state.company_table = future.result()
                st.session_state.company_table_revision = st.session_state.get('company_table_revision', 0) + 1
                st.session_state.pop('company_table_error', None)
            except Exception as exc:
                st.session_state.company_table_error = str(exc)
            st.session_state.pop('company_load', None)
            future = None
            loaded = 'company_table' in st.session_state
        if st.button('Refresh companies' if loaded else 'Show companies',
                     key='refresh_company_list', disabled=future is not None or deleting or preparation_running()):
            st.session_state.pop('company_table_error', None)
            st.session_state.company_load = company_loader().submit(load_companies)
            st.session_state.company_loading_started = True
            # Rerender immediately: disable the button and replace the old table.
            st.rerun()
        if 'company_load' in st.session_state:
            st.status('Loading saved companies and filing quarters…', state='running', expanded=False)
            return
        if st.session_state.get('company_table_error'):
            st.error('Unable to load the company list: ' + st.session_state.company_table_error)
        if 'company_table' in st.session_state:
            companies = st.session_state.company_table
            if companies:
                company_count = len({row['Ticker'] for row in companies})
                st.caption(f'{company_count} companies · {len(companies)} downloaded filings. Select fiscal-quarter rows to delete.')
                busy = bool(deletion and deletion['status'] in {'running', 'stopping'})
                selection_key = f"filing_selection_{st.session_state.get('company_table_revision', 0)}"
                if busy:
                    st.dataframe(companies, hide_index=True, use_container_width=True)
                    selected = []
                else:
                    table = st.dataframe(companies, hide_index=True, use_container_width=True,
                                         on_select='rerun', selection_mode='multi-row', key=selection_key)
                    selected = [{'ticker': companies[index]['Ticker'], 'accession': companies[index]['Accession']}
                                for index in table.selection.rows if 0 <= index < len(companies)]
                if selected:
                    st.caption('Selected: ' + '; '.join(f"{row['ticker']} / {row['accession']}" for row in selected))
                st.caption('Deletes only checked downloads and their graph/vector evidence. Other fiscal quarters are preserved.')
                if st.button(f'Delete selected downloads ({len(selected)})', disabled=busy or not selected, key='delete_filing_button'):
                    start('delete_filings', selections=selected)

            else:
                st.info('No company information is available yet. Add a company to start your research.')


companies_panel()
