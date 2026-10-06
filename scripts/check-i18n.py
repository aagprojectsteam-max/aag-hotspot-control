#!/usr/bin/python3
"""Check gettext coverage, translation format fields and committed MO parity."""
import ast
import gettext
import json
from pathlib import Path
import re
import string
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
MODULES=('gui.py','secret_dialog.py','tray.py','ui_support.py','i18n.py')


def check():
    source=ROOT/'lib/aag_hotspot'; messages=set();plurals=set()
    for name in MODULES:
        text=(source/name).read_text()
        if re.search('[\u0590-\u05ff]',text):raise ValueError('Hardcoded Hebrew in runtime UI')
        tree=ast.parse(text)
        parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call):continue
            fn=node.func.id if isinstance(node.func,ast.Name) else (node.func.attr if isinstance(node.func,ast.Attribute) else '')
            if name == 'i18n.py' and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id == '_catalog': continue
            if fn in ('_','gettext','ngettext'):
                if not node.args or not isinstance(node.args[0],ast.Constant):raise ValueError('Nonliteral gettext message')
                messages.add(node.args[0].value)
                if fn=='ngettext':plurals.add((node.args[0].value,node.args[1].value))
            # Constructors and label setters must translate literal visible text.
            for k in node.keywords:
                if k.arg in ('label','title','heading','body','tooltip_text','placeholder_text','description','comments','application_name'):
                    if isinstance(k.value,ast.Constant) and isinstance(k.value.value,str) and re.search('[A-Za-z]',k.value.value):
                        raise ValueError('Untranslated visible property in '+name)
            if fn in ('set_label','set_title','set_heading','set_description','set_tooltip_text','set_placeholder_text'):
                if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str) and re.search('[A-Za-z]',node.args[0].value):
                    raise ValueError('Untranslated visible setter in '+name)
    mo=source/'locale/he/LC_MESSAGES/aag-hotspot.mo'
    with mo.open('rb') as stream: catalog=gettext.GNUTranslations(stream)
    fmt=string.Formatter()
    def fields(value):return {field for _,field,_,_ in fmt.parse(value) if field is not None}
    for msg in messages:
        translated=catalog.gettext(msg)
        if msg not in catalog._catalog and (msg,0) not in catalog._catalog:raise ValueError('Missing translation: '+msg)
        if msg not in {s for s,_ in plurals} and fields(translated)!=fields(msg):raise ValueError('Translation placeholders differ')
    for singular,plural in plurals:
        for count in (0,1,2,10,100):
            translated=catalog.ngettext(singular,plural,count)
            # Natural singular Hebrew may omit {count} ("one minute").
            if not fields(translated)<=fields(singular):raise ValueError('Unexpected plural fields')
    with tempfile.TemporaryDirectory() as directory:
        compiled=Path(directory)/'check.mo'
        subprocess.run(['msgfmt','--check','-o',str(compiled),str(ROOT/'po/he.po')],check=True,timeout=15)
        if compiled.read_bytes()!=mo.read_bytes():raise ValueError('Committed MO is stale')
    return {'passed':True,'translated_messages':len(messages),'plural_messages':len(plurals),'runtime_hebrew_literals':0,'compiled_catalog_matches':True}


if __name__=='__main__':print(json.dumps(check()))
