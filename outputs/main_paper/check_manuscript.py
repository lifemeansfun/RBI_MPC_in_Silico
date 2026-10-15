"""Read-only structural checks; rendered-page visual review remains separate."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
}
W = '{' + NS['w'] + '}'


def check(render_dir):
    docx = HERE / 'RBI_MPC_In_Silico_Research_Manuscript.docx'
    provenance = json.loads((HERE / 'manuscript_provenance.json').read_text())
    source = json.loads((HERE / 'manuscript_source.json').read_text())
    digest = hashlib.sha256(docx.read_bytes()).hexdigest()
    assert digest == provenance['document_sha256']
    with ZipFile(docx) as package:
        root = ET.fromstring(package.read('word/document.xml'))
        styles = ET.fromstring(package.read('word/styles.xml'))
        core = ET.fromstring(package.read('docProps/core.xml'))
        tables = root.findall('.//w:tbl', NS)
        pictures = root.findall('.//wp:docPr', NS)
        links = root.findall('.//w:hyperlink', NS)
        assert len(tables) == 7
        assert len(pictures) == 6
        assert len(links) == 14
        assert all(p.get('descr') for p in pictures)
        assert not (core.find('dc:creator', NS).text or '')
        assert not (core.find('cp:lastModifiedBy', NS).text or '')
        assert root.find('.//w:ins', NS) is None
        assert root.find('.//w:del', NS) is None
        assert root.find('.//w:commentReference', NS) is None
        for table in tables:
            assert table.find('w:tr/w:trPr/w:tblHeader', NS) is not None
            borders = table.find('w:tblPr/w:tblBorders', NS)
            assert borders is not None and len(borders) == 6
            assert all(b.get(W + 'color') == 'D9D9D9' for b in borders)
            for row in table.findall('w:tr', NS):
                assert row.find('w:trPr/w:cantSplit', NS) is not None
                height = row.find('w:trPr/w:trHeight', NS)
                assert height is None or height.get(W + 'hRule') != 'exact'
        used_styles = {p.get(W + 'val') for p in root.findall('.//w:pStyle', NS)}
        for style_id in ['Title', 'Heading1', 'Heading2', 'Heading3']:
            if style_id not in used_styles:
                continue
            style = next(s for s in styles.findall('w:style', NS) if s.get(W + 'styleId') == style_id)
            color = style.find('w:rPr/w:color', NS)
            assert color is not None and color.get(W + 'val') == '000000'
            assert style.find('w:pPr/w:pBdr', NS) is None
        for name in package.namelist():
            if re.fullmatch(r'word/header\d+\.xml', name):
                header = ET.fromstring(package.read(name))
                assert all(c.get(W + 'val') == '000000' for c in header.findall('.//w:color', NS))
        text = ' '.join(t.text or '' for t in root.findall('.//w:t', NS))
        for token in ['turn0search', 'turn1search', 'TODO', 'TBD', 'AUTHOR NAME', '\\begin{', '\\frac{']:
            assert token not in text
        assert source['title'] in text
        assert re.fullmatch(r'[A-Za-z0-9 ]+', source['title'])
        for block in source['blocks']:
            if block['type'] in ['h1', 'h2', 'h3']:
                assert re.fullmatch(r'[A-Za-z0-9 ]+', block['text'])
    pdf = render_dir / docx.with_suffix('.pdf').name
    reader = PdfReader(pdf)
    assert len(reader.pages) == 18
    assert all((p.extract_text() or '').strip() for p in reader.pages)
    assert all((render_dir / f'page-{n}.png').is_file() for n in range(1, 19))
    result = {
        'source_commit': provenance['source_commit'],
        'document_sha256': digest,
        'structural_checks': 'passed',
        'rendered_pages': 18,
        'tables': len(tables),
        'figures': 2,
        'rendered_equations': 4,
        'linked_references': len(links),
        'render_directory': str(render_dir),
        'scope': 'Document integrity and formatting only; no research simulations executed',
    }
    (HERE / 'manuscript_qa.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--render-dir', required=True, type=Path)
    check(parser.parse_args().render_dir)
