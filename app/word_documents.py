"""Extract resume text without executing Word macros or fetching external resources."""
import io
import os
import shutil
import sys
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from .errors import DomainError


def extract_word(content: bytes, filename: str) -> str:
    if filename.lower().endswith('.docx'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > 50 * 1024 * 1024:
                    raise DomainError('DOCUMENT_LENGTH', 'Word 解压后过大，请精简后导入。', 422)
                raw = archive.read('word/document.xml')
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('XML declarations are not allowed')
            root = ET.fromstring(raw)
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            paragraphs = []
            for paragraph in root.iter(ns + 'p'):
                parts = []
                for node in paragraph.iter():
                    if node.tag == ns + 't': parts.append(node.text or '')
                    elif node.tag == ns + 'tab': parts.append('\t')
                    elif node.tag in (ns + 'br', ns + 'cr'): parts.append('\n')
                paragraphs.append(''.join(parts))
            text = '\n'.join(paragraphs)
        except DomainError:
            raise
        except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as exc:
            raise DomainError('WORD_INVALID', 'DOCX 文件损坏、加密或格式不符，请另存为未加密的 DOCX 后导入。', 422) from exc
    else:
        if not content.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
            raise DomainError('WORD_INVALID', 'DOC 文件格式不符，请用 Word 另存为 DOCX 后导入。', 422)
        executable = shutil.which('antiword')
        local_tools = Path(sys.prefix) / 'tools' / 'antiword'
        local_executable = local_tools / 'bin' / 'antiword.exe'
        environment = {**os.environ, 'LC_ALL': 'C.UTF-8'}
        if not executable and sys.platform == 'win32' and local_executable.is_file():
            executable = str(local_executable)
            environment['ANTIWORDHOME'] = str(local_tools / 'share' / 'antiword')
        if not executable:
            raise DomainError('WORD_PARSER_UNAVAILABLE', '当前服务尚未安装 DOC 解析器 antiword，请安装后重启服务，或另存为 DOCX 导入。', 503)
        with tempfile.TemporaryDirectory(prefix='tongpin-word-') as directory:
            path = Path(directory) / 'resume.doc'; path.write_bytes(content)
            try:
                result = subprocess.run([executable, '-m', 'UTF-8.txt', str(path)], capture_output=True, timeout=15, env=environment, cwd=str(local_tools / 'bin') if sys.platform == 'win32' and local_executable.is_file() else None)
            except subprocess.TimeoutExpired as exc:
                raise DomainError('DOCUMENT_TIMEOUT', 'Word 文件解析超时，请另存为 DOCX 后导入。', 422) from exc
        if result.returncode:
            raise DomainError('WORD_INVALID', 'DOC 无法解析或已加密，请另存为未加密的 DOCX 后导入。', 422)
        text = result.stdout.decode('utf-8', errors='replace')
    text = text.replace('\x00', '').strip()
    if len(text) > 50000:
        raise DomainError('DOCUMENT_LENGTH', '简历正文最多 50000 字，请精简后导入。', 422)
    if not text:
        raise DomainError('WORD_EMPTY', 'Word 中没有可提取的正文；图片简历请先进行文字识别。', 422)
    return text
