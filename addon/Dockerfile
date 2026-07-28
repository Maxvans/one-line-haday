ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py /app/

EXPOSE 8099
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099"]
