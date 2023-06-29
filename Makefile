run:
	docker run --rm -it -p 8000:8000 \
		-v `pwd`/dev_jupyterhub_config.py:/srv/jupyterhub/jupyterhub_config.py \
		-v `pwd`:/data \
		-e CREATE_DEFAULT_NAAS_USER=true \
		jupyterhub/jupyterhub:1.3 \
		bash -c 'pip install -e /data && jupyterhub'
	make run

get-db:
	docker cp `docker ps | grep 'jupyterhub/jupyterhub' | awk '{print $$1}'`:/srv/jupyterhub/jupyterhub.sqlite jupyterhub.sqlite``

sh:
	docker exec -it `docker ps | grep 'jupyterhub/jupyterhub' | awk '{print $$1}'` bash

