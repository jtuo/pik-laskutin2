# pik-laskutin2
Custom invoicing software for [Polyteknikkojen ilmailukerho](https://www.pik.fi)

Rewrite of the old invoicing software.

## Installation


```bash	
# Install miniconda if not already installed
conda create -n pik-laskutin python=3.10
conda activate pik-laskutin

git clone https://github.com/jtuo/pik-laskutin2.git
cd pik-laskutin2
pip install -r requirements.txt
```

## Running the application
```bash
# List available commands
python manage.py

# Run the user interface
python manage.py runserver
```

