run:
	docker run --rm -it -p 8000:8000 \
		-v `pwd`/dev_jupyterhub_config.py:/srv/jupyterhub/jupyterhub_config.py \
		-v `pwd`:/data \
		jupyterhub/jupyterhub \
		bash -c 'pip install -e /data && jupyterhub'
	make run