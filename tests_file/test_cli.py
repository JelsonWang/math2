import json
import zipfile
import pytest
from math2_pack.__main__ import main,read_return

@pytest.mark.parametrize('command',['init','validate','build-daily','build-specialty','import-return','coverage-report','export-history','verify-release'])
def test_every_command_has_help_without_bank_or_server(command,capsys):
    with pytest.raises(SystemExit) as result:main([command,'--help'])
    assert result.value.code==0
    assert 'usage:' in capsys.readouterr().out

def test_json_duplicate_keys_and_nonfinite_constants_are_rejected(tmp_path):
    path=tmp_path/'card.json';path.write_text('{"a":1,"a":2}',encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate'):read_return(path)
    path.write_text('{"x":NaN}',encoding='utf-8')
    with pytest.raises(ValueError,match='Nonfinite'):read_return(path)

def test_return_zip_path_and_duplicate_entries_are_rejected(tmp_path):
    path=tmp_path/'return.zip'
    with zipfile.ZipFile(path,'w') as archive:archive.writestr('../DAILY_RETURN.json','{}')
    with pytest.raises(ValueError,match='Unsafe'):read_return(path)
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('DAILY_RETURN_a.json','{}');archive.writestr('DAILY_RETURN_b.json','{}')
    with pytest.raises(ValueError,match='exactly one'):read_return(path)
