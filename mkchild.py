import coverage,glob,json,os
res={}
for l in open('/tmp/br/poolmap.txt'):
    n,t=l.strip().split(' ',1)
    fs=glob.glob(f'/tmp/br/cov4/{n}/cov.*')
    c=coverage.Coverage(data_file=f'/tmp/br/cov4/{n}.data'); c.combine(fs,keep=True)
    d=c.get_data(); d.read()
    res[t]={f:sorted(d.lines(f) or []) for f in d.measured_files()}
json.dump(res,open('/tmp/br/childcov.json','w'))
print(len(res), sum(len(v) for r in res.values() for v in r.values()))
