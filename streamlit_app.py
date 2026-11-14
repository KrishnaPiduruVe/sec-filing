"""Run: python -m streamlit run streamlit_app.py --server.address 127.0.0.1"""
import html
import time
import re
import streamlit as st

from sec_web_jobs import JobManager, inventory
from answer_display import readable_answer, answer_markdown

st.set_page_config(page_title='SEC Filing Workspace', page_icon='📄', layout='wide',
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
.running .circle {background:#eff6ff;border-color:#2563eb;color:#2563eb;animation:pulse 1.3s infinite}
.running strong {color:#2563eb}
.completed .circle {background:#f0fdf4;border-color:#16a34a;color:#15803d}
.failed .circle,.stopped .circle {background:#fef2f2;border-color:#dc2626;color:#dc2626}
@keyframes pulse {50% {box-shadow:0 0 0 8px #2563eb20}}
@media(prefers-reduced-motion:reduce){.running .circle{animation:none}}
</style>''', unsafe_allow_html=True)


@st.cache_resource
def workflow_task_runner():
    return JobManager()


runner = workflow_task_runner()


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
    st.title('Insights on publicly traded companies')
    st.caption('Explore financial performance, business risks, and strategic developments through SEC filings.')
with settings_column:
    with st.popover('⚙️', help='Research settings'):
        st.subheader('Settings')
        mode = st.selectbox('Answer using', ['hybrid', 'graph', 'vector'])
        top_k = st.number_input('Context items per source', 1, 50, 12)
        with st.expander('Preparation settings'):
            batch_size = st.number_input('Chunks per batch', 1, 100, 5)
            batch_delay = st.number_input('Pause between batches (seconds)', 0, 600, 65)
        st.divider()
        st.markdown('**Appearance**')
        appearance = st.selectbox('Theme', ['Light', 'Dark'], index=1)
        text_size = st.select_slider('Text size', options=['Small', 'Medium', 'Large'], value='Medium')

palette = ({'background': '#0e1117', 'surface': '#1b2130', 'text': '#f1f5f9', 'muted': '#b4c0d4', 'border': '#475569'}
           if appearance == 'Dark' else
           {'background': '#ffffff', 'surface': '#f8fafc', 'text': '#172033', 'muted': '#526174', 'border': '#cbd5e1'})
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
[data-testid="stButton"] button[kind="secondary"], [data-testid="stPopover"] button {{background:{palette['surface']}; color:{palette['text']}; border-color:{palette['border']}}}
</style>""", unsafe_allow_html=True)


def workflow(job):
    if not job or job['action'] != 'prepare':
        return
    if job['status'] == 'completed':
        finished = job.get('finished_at', job.get('started', 0) + job.get('elapsed', 0))
        if time.time() - finished < 10:
            from company_inventory import company_label
            symbols = job.get('tickers') or st.session_state.get('preparing_tickers', [])
            if symbols:
                key = 'company_labels_' + job['id']
                if key not in st.session_state:
                    st.session_state[key] = ', '.join(company_label(t) for t in symbols)
                st.success(f"Information for {st.session_state[key]} is ready. Ask a question above.")
        return
    st.subheader('Preparing your information')
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
        st.warning('Preparation ' + job['status'] + '. Completed files are saved; click Download again to finish missing stages.')
    if job['status'] in {'running', 'stopping'} and st.button('Stop preparation', disabled=job['status'] == 'stopping'):
        runner.stop()
        st.rerun(scope='fragment')
    with st.expander('Preparation details', expanded=job['status'] == 'failed'):
        st.code(job['output'] or 'Starting…', language='text')


st.subheader('What would you like to know?')
st.caption('Ask across available companies, or mention a company or ticker to focus your question.')
with st.form('question_form'):
    question = st.text_area('Your question', placeholder='What are the key risks facing Apple? How do revenue trends compare across companies?', max_chars=5000)
    ask = st.form_submit_button('Explore insights', type='primary')
if ask:
    start('query', question=question, mode=mode, top_k=top_k)


@st.fragment(run_every='1s')
def answer_panel():
    job = runner.snapshot()
    if job and job['action'] == 'query':
        output = job['output'].strip()
        if job['status'] in {'running', 'stopping'}:
            st.info('Reading your saved information…' if job['status'] == 'running' else 'Stopping…')
            if st.button('Stop task', disabled=job['status'] == 'stopping'):
                runner.stop()
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
    state = inventory()
    if not state['env_exists']:
        st.warning('Configure .env before preparing filings or asking questions.')


answer_panel()


@st.fragment(run_every='1s')
def preparation_panel():
    job = runner.snapshot()
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
    if st.button('View token usage'):
        st.session_state.show_token_usage = True
    if st.session_state.get('show_token_usage'):
        from token_usage import usage_summary
        try:
            usage_rows = usage_summary()
            if usage_rows:
                columns = ['Operation', 'Input tokens', 'Output tokens', 'Events', 'Estimated events']
                st.dataframe([dict(zip(columns, row)) for row in usage_rows],
                             hide_index=True, use_container_width=True)
            else:
                st.info('No token usage has been recorded yet.')
        except Exception as exc:
            st.error(f'Unable to read token usage: {exc}')

with st.expander('Available company information'):
    if st.button('Show companies'):
        st.session_state.show_companies = True
    if st.session_state.get('show_companies'):
        from company_inventory import company_information
        try:
            companies = company_information()
            if companies:
                st.dataframe(companies, hide_index=True, use_container_width=True)
            else:
                st.info('No company information is available yet. Add a company to start your research.')
        except Exception as exc:
            st.error(f'Unable to read company information: {exc}')

