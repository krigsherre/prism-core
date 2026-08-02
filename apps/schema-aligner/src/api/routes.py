from fastapi import APIRouter, HTTPException
from aiokafka import AIOKafkaClient
from config.settings import settings

router = APIRouter()

@router.get("/healthz")
async def healthz():
    return {"status": "ok"}

@router.get("/readyz")
async def readyz():
    client = AIOKafkaClient(bootstrap_servers=settings.kafka_broker)
    try:
        await client.bootstrap()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Kafka unreachable: {str(e)}")
    finally:
        await client.close()
