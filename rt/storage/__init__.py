"""
rt.storage
Dove vivono i file delle lezioni: nella cartella della lezione (storage "folder", layout
storico) oppure nel database con i media in un'unica cartella media/ (storage "db").
Il resto di RT passa da rt.storage.fs, che offre le stesse operazioni di os/open/shutil
e sceglie il backend giusto per ogni percorso.
"""
