from pathlib import Path

p = Path('ssm/financial_recapitalization.py')
s = p.read_text()
old = """    # Accession or mere proximity is never a financing/retirement join.
    # Unlinked retirements retain separate event identities, even when there
    # is only one issuance somewhere in the same financial filing.
    for row in retired:
        if linked[id(row)] is None:
            issuances.append({'date':row['transaction_date'],'shares':0,'name':None,'alternative':False,
                              'evidence':'Retirement only; related financing is unresolved.', 'retirement_only':row})
    records=[]"""
new = """    # Accession or mere proximity is never a financing/retirement join.
    # Unlinked retirements retain separate event identities. Return those
    # evidence-only records first so the public API continues to surface an
    # unresolved retirement without implying it belongs to a nearby issuance.
    standalone=[]
    for row in retired:
        if linked[id(row)] is None:
            standalone.append({'date':row['transaction_date'],'shares':None,'name':None,'alternative':False,
                               'evidence':'Retirement only; related financing is unresolved.', 'retirement_only':row})
    issuances=standalone+issuances
    records=[]"""
if old not in s:
    raise SystemExit('standalone retirement compatibility block not found')
p.write_text(s.replace(old, new, 1))
