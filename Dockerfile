FROM fnproject/python:3.8 as build-image

COPY function.py /function/

ENV FN_HANDLER="function.handler"
