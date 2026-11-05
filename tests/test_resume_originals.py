"""Preserve uploaded bytes without extending application consent or ownership."""
from io import BytesIO
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.models import ResumeInput
from test_hiring import scene, apply_body
from test_applicant_resume_import import import_row


def pdf_bytes():
    writer = PdfWriter()
    for number in (1, 2):
        page = writer.add_blank_page(width=595, height=842)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'0.3 0.2 0.6 rg 0 700 595 142 re f BT /F1 18 Tf 50 640 Td (Synthetic resume page {number}: Python API project 13812345678) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def upload(client, filename='演示简历.pdf', content=None):
    content = pdf_bytes() if content is None else content
    result = client.post('/resumes/batch', data={'data_origin': 'synthetic'}, files={'files': (filename, content)})
    assert result.status_code == 200, result.text
    assert result.json()['errors'] == [], result.text
    return result.json()['resumes'][0], content


def test_pdf_original_is_byte_identical_owner_only_and_analysis_stays_redacted(scene):
    app, recruiter, _, owner, outsider, guest, _, _, _ = scene
    resume, original = upload(owner)
    endpoint = '/resumes/' + resume['id'] + '/original'
    assert resume['original_file'] == {'name': '演示简历.pdf', 'media_type': 'application/pdf', 'size': len(original)}
    assert not {'original_file_key', 'raw_file_path', 'source_hash'} & resume.keys()
    assert '13812345678' not in resume['text']
    result = owner.get(endpoint)
    assert result.content == original
    assert result.headers['content-type'] == 'application/pdf'
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-content-type-options'] == 'nosniff'
    assert "filename*=utf-8''" in result.headers['content-disposition'].lower()
    for client, status in ((guest, 401), (outsider, 404), (recruiter, 404)):
        assert client.get(endpoint).status_code == status
    assert owner.get('/resumes/' + resume['id'] + '/download').content.decode('utf-8-sig') == resume['text']
    assert any(row['id'] == resume['id'] and row['original_file'] for row in owner.get('/resumes').json())
    assert owner.delete('/resumes/' + resume['id']).status_code == 200
    assert owner.get(endpoint).status_code == 404


@pytest.mark.parametrize('filename,content,media_type', [
    ('resume.txt', '项目经历：使用 Python 开发并测试订单接口，整理接口文档。'.encode(), 'text/plain'),
    ('resume.json', b'{"name":"Synthetic","text":"Python API development and testing project experience"}', 'application/json'),
])
def test_text_and_json_uploads_keep_original_bytes(scene, filename, content, media_type):
    _, _, _, owner, _, _, _, _, _ = scene
    resume, original = upload(owner, filename, content)
    assert resume['original_file']['media_type'] == media_type
    assert owner.get('/resumes/' + resume['id'] + '/original').content == original


def test_original_never_enters_authorized_application_snapshot_or_recruiter_import(scene):
    _, recruiter, _, owner, _, _, _, job, _ = scene
    resume, _ = upload(owner)
    application = owner.post('/applications', json=apply_body(job, resume)).json()
    assert 'original_file' not in str(application['resume_snapshot'])
    assert recruiter.get('/resumes/' + resume['id'] + '/original').status_code == 404
    imported = import_row(recruiter, application).json()['resume']
    assert 'original_file' not in imported
    assert recruiter.get('/resumes/' + imported['id'] + '/original').status_code == 404
    assert recruiter.get('/applications/' + application['id'] + '/resume-download').content.decode('utf-8-sig') == resume['text']


def test_legacy_missing_and_outside_storage_files_fail_explicitly(scene, tmp_path):
    app, _, _, owner, _, _, _, _, legacy = scene
    assert owner.get('/resumes/' + legacy['id'] + '/original').json()['detail']['code'] == 'ORIGINAL_UNAVAILABLE'
    resume, _ = upload(owner)
    outside = tmp_path / 'outside.pdf'; outside.write_bytes(b'private non-resume data')
    app.state.service.db.update('resumes', resume['id'], {'original_file_key': '../outside.pdf'})
    assert owner.get('/resumes/' + resume['id'] + '/original').status_code == 404
    app.state.service.db.update('resumes', resume['id'], {'original_file_key': 'missing.pdf'})
    assert owner.get('/resumes/' + resume['id'] + '/original').status_code == 404


def test_failed_import_rolls_back_bytes_and_database(scene, monkeypatch):
    app, _, _, owner, _, _, users, _, _ = scene
    service = app.state.service
    folder = service.settings.data_dir / 'raw_files'
    files = set(folder.iterdir())
    original_insert = service.db.insert
    def fail_resume(table, *args, **kwargs):
        if table == 'resumes': raise RuntimeError('synthetic database failure')
        return original_insert(table, *args, **kwargs)
    monkeypatch.setattr(service.db, 'insert', fail_resume)
    with pytest.raises(RuntimeError):
        service.create_resume(ResumeInput(name='Synthetic', text='Python API project with tests and documentation.', data_origin='synthetic'), users[2]['actor'], ('resume.pdf', pdf_bytes()))
    assert set(folder.iterdir()) == files
    assert len(owner.get('/resumes').json()) == 1


def test_invalid_upload_does_not_create_material_or_original(scene):
    app, _, _, owner, _, _, _, _, _ = scene
    folder = app.state.service.settings.data_dir / 'raw_files'
    files = set(folder.iterdir())
    result = owner.post('/resumes/batch', data={'data_origin': 'synthetic'}, files={'files': ('broken.pdf', b'not a PDF')}).json()
    assert result['errors'] and not result['resumes']
    assert set(folder.iterdir()) == files


def test_manual_revision_does_not_misrepresent_original_pdf_as_updated_content(scene):
    _, _, _, owner, _, _, _, _, _ = scene
    resume, original = upload(owner)
    session = owner.post('/ai/workspaces', json={'resume_id': resume['id']}).json()
    from uuid import uuid4
    result = owner.post('/ai/workspaces/' + session['id'] + '/materials/edit', json={
        'kind': 'resume', 'title': '修改后的合成简历', 'text': resume['text'] + '\nProject: added API testing experience.',
        'expected_version': session['version'], 'request_id': str(uuid4())})
    assert result.status_code == 200, result.text
    revised = result.json()['resume']
    assert revised['id'] != resume['id'] and 'original_file' not in revised
    assert owner.get('/resumes/' + revised['id'] + '/original').status_code == 404
    assert owner.get('/resumes/' + resume['id'] + '/original').content == original
