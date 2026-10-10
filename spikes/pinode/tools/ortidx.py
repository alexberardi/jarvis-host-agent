import re,sys
src=open(sys.argv[1]).read()
i=src.index('\nstruct OrtApi {'); j=src.index('\n};',i)
body=src[i:j]
body=re.sub(r'/\*.*?\*/','',body,flags=re.S); body=re.sub(r'//[^\n]*','',body)
assert '#if' not in body, 'preprocessor in struct'
pat=re.compile(r'ORT_API2_STATUS\(\s*(\w+)|ORT_CLASS_RELEASE\(\s*(\w+)\s*\)|ORT_API_T\(\s*[^,]+?,\s*(\w+)|ORT_API_CALL\s*\*\s*(\w+)\s*\)')
names=[]
for m in pat.finditer(body):
    a,b,c,d=m.groups()
    names.append(a or ('Release'+b if b else None) or c or d)
want=sys.argv[2:]
print(len(names))
for w in want: print(w, names.index(w))
