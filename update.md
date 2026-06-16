# Dataset Review

## 1. Dataset Reception
- Received the Bilal dataset extraction covering 1996 to 2022 from Duisburg University ([Zenodo link](https://zenodo.org/records/3819374))

## 2. Data Quality Check
- Performed a data quality check, assuming the dataset was extracted from PDF sources only
- The extraction worked well, especially for data previously unsupported by any other official source
- The first two years are missing. Contacted Bilal to determine whether the issue stems from the extraction process or the dataset itself

## 3. Data Augmentation
- Augmented the data by adding information on deputies from the 10th and 11th legislatures using a second source
- Cross-validated the data for the 12th to 16th legislatures to ensure accuracy

## 4. Golden Review
- My dad finalized the golden review in a second column, as discussed

## 5. Documentation
- finish it and share it to nina and kamil

- explicité le probleme avec le format et les nombres extrait qui sont des erreurs (probleme d'article + president assigné par erreur a certain endroit)
- connecté a la db, voir le format attendu pour policorp, shape mon jeu de donnée a ce qui est attendu et push sur la db francaise 

## 6. Next Steps
Overall, the dataset shape is good. Still need to:
- Merge the two speech datasets to ensure a uniform shape
- Push the datasets to the VM
- Code the French handler


## Pipeline refacto
Le dossier `refacto` contient une entree CLI unique :
```bash
python3 refacto/main.py --help
```
Par defaut, le pipeline utilise :
- `refacto/raw` pour les XML bruts
- `refacto/converted` pour les JSON convertis
- `refacto/centralized_speeches.csv` pour le CSV final
Commandes disponibles :
```bash
python3 refacto/main.py download --years 2011-2026
python3 refacto/main.py convert
python3 refacto/main.py csv
python3 refacto/main.py all --years 2011-2026
```
Si les XML sont deja presents dans `refacto/raw`, lancer tout le pipeline sans telecharger :
```bash
python3 refacto/main.py all --skip-download
```