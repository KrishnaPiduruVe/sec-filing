"""Delete selected ticker/accession downloads and their graph/vector evidence."""
import argparse
import json
from pathlib import Path
import re
import shutil

from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

ROOT = DATA_ROOT


def validate_selections(selections):
    if (
        not isinstance(selections, list)
        or not 1 <= len(selections) <= SETTINGS.limits.filing_delete_selections
    ):
        raise ValueError(
            f"Select 1–{SETTINGS.limits.filing_delete_selections} downloaded filings."
        )
    result = []
    for item in selections:
        if not isinstance(item, dict):
            raise ValueError('Invalid filing selection.')
        ticker = str(item.get('ticker', '')).upper()
        accession = str(item.get('accession', ''))
        if not re.fullmatch(
            rf"[A-Z][A-Z0-9.-]{{0,{SETTINGS.limits.ticker_symbol_chars - 1}}}",
            ticker,
        ) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
            raise ValueError('Invalid ticker or accession in selection.')
        selection = {'ticker': ticker, 'accession': accession}
        if selection not in result:
            result.append(selection)
    return result


def write_graph(graph, path):
    import networkx as nx
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.graphml.tmp')
    nx.write_graphml(graph, temporary)
    temporary.replace(path)


def delete_filings(selections):
    import networkx as nx
    selections = validate_selections(selections)
    targets = {(item['ticker'], item['accession']) for item in selections}
    filings_root = ROOT / SETTINGS.paths.filings_dir
    graphs_root = ROOT / SETTINGS.paths.graph_dir
    vector_root = ROOT / SETTINGS.paths.vector_dir
    for ticker, accession in targets:
        for path in (
            filings_root / ticker,
            filings_root / ticker / accession,
            graphs_root / f'{ticker}.graphml',
        ):
            if path.is_symlink():
                raise ValueError('Refusing to delete linked company data.')
    # Preflight graph reads so corrupt graphs fail before any deletion.
    graphs = {p.stem: nx.read_graphml(p, force_multigraph=True)
              for p in graphs_root.glob('*.graphml') if p.stem != 'combined'}
    combined_path = graphs_root / 'combined.graphml'
    legacy = nx.read_graphml(combined_path, force_multigraph=True) if not graphs and combined_path.is_file() else None

    def prune(graph, ticker=None):
        remove = [(u, v, k) for u, v, k, d in graph.edges(keys=True, data=True)
                  if (str(d.get('ticker', ticker or '')), str(d.get('filing', ''))) in targets]
        graph.remove_edges_from(remove)
        graph.remove_nodes_from(list(nx.isolates(graph)))
        # Node evidence merges multiple quarters in the original graph. Rebuild
        # it from retained relationships so deleted-quarter quotes cannot linger.
        for node in graph:
            evidence = {str(d['evidence']) for _, _, d in list(graph.in_edges(node, data=True)) + list(graph.out_edges(node, data=True)) if d.get('evidence')}
            graph.nodes[node]['evidence'] = ' | '.join(sorted(evidence))[
                :SETTINGS.graph.max_evidence_chars
            ]
        return graph

    for ticker in {t for t, _ in targets}:
        if ticker in graphs:
            prune(graphs[ticker], ticker)
    if legacy is not None:
        prune(legacy)
    if vector_root.is_dir():
        import chromadb
        client = chromadb.PersistentClient(path=str(vector_root))
        try:
            collection = client.get_collection(SETTINGS.paths.vector_collection)
        except chromadb.errors.NotFoundError:
            collection = None
        if collection is not None:
            for ticker, accession in targets:
                collection.delete(where={'$and': [{'ticker': ticker}, {'filing': accession}]})
    for ticker, accession in sorted(targets):
        folder = filings_root / ticker / accession
        if folder.exists():
            shutil.rmtree(folder)
        parent = folder.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    for ticker in {t for t, _ in targets}:
        if ticker in graphs:
            path = graphs_root / f'{ticker}.graphml'
            remaining_html = [
                p
                for p in (filings_root / ticker).glob('*/*')
                if p.suffix.lower() in {'.htm', '.html'}
            ]
            if remaining_html or graphs[ticker].number_of_edges():
                write_graph(graphs[ticker], path)
            else:
                path.unlink(missing_ok=True)
                del graphs[ticker]
    combined = legacy if legacy is not None else nx.MultiDiGraph()
    if legacy is None:
        for graph in graphs.values():
            combined = nx.compose(combined, graph)
    if combined_path.exists() or graphs:
        write_graph(combined, combined_path)
    for ticker, accession in sorted(targets):
        print(f'Deleted {ticker} filing {accession} and its indexed data.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selections', required=True)
    args = parser.parse_args()
    delete_filings(json.loads(args.selections))
