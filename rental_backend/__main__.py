import uvicorn
from rental_backend.routes.base import app

if __name__ == '__main__':
    uvicorn.run(app)
