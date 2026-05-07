FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake whatever holyhub.db is in the build context as a seed for the /data
# volume. On first container start with an empty volume, the entrypoint copies
# this seed into /data/holyhub.db so the app launches with real data. After
# that, the volume is the source of truth and the seed is ignored.
RUN if [ -f holyhub.db ]; then mv holyhub.db holyhub.db.seed; fi

EXPOSE 8000

CMD ["/app/scripts/docker-entrypoint.sh"]
