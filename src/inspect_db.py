import sqlite3
from pathlib import Path
DB=Path(__file__).resolve().parents[1]/'data'/'smash_wm.db'
con=sqlite3.connect(DB)
print('Players:',con.execute('select count(*) from players').fetchone()[0])
print('Tournaments:',con.execute('select count(*) from tournaments').fetchone()[0])
print('\nTitles:')
for name,n in con.execute("select p.display_name,count(*) from tournaments t join players p on p.player_id=t.winner_id group by p.player_id order by count(*) desc,p.display_name"):
 print(f'{name}: {n}')
con.close()
