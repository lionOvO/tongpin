from io import BytesIO
from zipfile import ZipFile
import pytest
from app.word_documents import extract_word
from app.errors import DomainError
from test_hiring import scene


def docx_bytes(xml=None):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', xml or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>合成简历 Python API 项目开发与测试，电话13812345678</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>教育经历：计算机科学与技术</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    return output.getvalue()


def test_word_import_keeps_original_and_extracts_paragraphs_and_tables(scene):
    _, recruiter, _, owner, outsider, _, _, _, _ = scene
    content = docx_bytes()
    result = owner.post('/resumes/batch', data={'data_origin': 'synthetic'}, files={'files': ('合成简历.docx', content)}).json()
    assert not result['errors'], result
    resume = result['resumes'][0]
    assert '教育经历：计算机科学与技术' in resume['text']
    assert '13812345678' not in resume['text']
    assert resume['original_file']['media_type'].endswith('wordprocessingml.document')
    endpoint = '/resumes/' + resume['id'] + '/original'
    assert owner.get(endpoint).content == content
    assert recruiter.get(endpoint).status_code == outsider.get(endpoint).status_code == 404


@pytest.mark.parametrize('content,name', [(b'not word', 'broken.docx'), (b'not word', 'broken.doc'), (docx_bytes('<!DOCTYPE x [<!ENTITY a "secret">]><x>&a;</x>'), 'unsafe.docx')])
def test_invalid_word_rejected(content, name):
    with pytest.raises(DomainError): extract_word(content, name)


def test_doc_uses_bounded_non_shell_parser(monkeypatch):
    import app.word_documents as module
    from types import SimpleNamespace
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/antiword')
    def run(args, **kwargs):
        assert args[:3] == ['/usr/bin/antiword', '-m', 'UTF-8.txt']
        assert kwargs['timeout'] == 15
        assert not kwargs.get('shell')
        return SimpleNamespace(returncode=0, stdout='合成简历：Python 项目开发与维护经验。'.encode())
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert 'Python' in extract_word(bytes.fromhex('D0CF11E0A1B11AE1'), 'resume.doc')
