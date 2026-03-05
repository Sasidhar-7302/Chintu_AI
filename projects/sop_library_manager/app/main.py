from fastapi import FastAPI

app = FastAPI(title='SOP Library Manager')

@app.get('/health')
def health():
    return {'status': 'ok'}
