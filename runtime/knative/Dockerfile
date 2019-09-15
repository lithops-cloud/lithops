FROM ibmfunctions/action-python-v3.6:master

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY pywren_ibm_cloud ./pywren_ibm_cloud

COPY runtime/knative/app.py ./

RUN pip install Flask gunicorn

# Run the web service on container startup.

ENV PORT 8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 app:app
