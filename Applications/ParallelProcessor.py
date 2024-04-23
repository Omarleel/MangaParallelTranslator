import logging
import os
import torch
import torch.multiprocessing as mp
from Applications.JsonGenerator import JsonWriter
from Applications.Utilities import Utilities
from Utils.Constantes import PESO_MODELOS

logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('debug.log')
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

class ParallelProcessor:
    def __init__(self):
        self.utilities = Utilities()
        mp.set_start_method('spawn', force=True)
        if torch.cuda.is_available():
            device = torch.device("cuda")
            properties = torch.cuda.get_device_properties(device)
            self.multi_processor_count = properties.multi_processor_count
            self.total_memory_gb = properties.total_memory / 1024**3  # En Gb
    
    def procesar_en_paralelo(self, ruta_carpeta_entrada, ruta_carpeta_salida, process_func, batch_size = 8):
        try:
            archivos = os.listdir(ruta_carpeta_entrada)
            lista_imagenes = [
                archivo for archivo in archivos if archivo.lower().endswith(('.jpg', '.png', '.jpeg', '.bmp'))
            ]
            cantidad_archivos = len(lista_imagenes)
            # Dividir las imágenes en lotes para procesamiento paralelo
            lotes_imagenes =  [lista_imagenes[i:i+batch_size] for i in range(0, cantidad_archivos, batch_size)]
            num_processes = len(lotes_imagenes)
            while num_processes > self.multi_processor_count or num_processes * PESO_MODELOS > self.total_memory_gb:
                batch_size += 1
                logger.info(f"La memoria GPU es insuficiente, se reasignara un batch_size de {batch_size}")
                lotes_imagenes =  [lista_imagenes[i:i+batch_size] for i in range(0, cantidad_archivos, batch_size)]
                num_processes = len(lotes_imagenes)
                if batch_size >= cantidad_archivos:
                    break

            lotes_imagenes = self.utilities.convertir_a_diccionarios(lotes_imagenes)
            ruta_limpieza_salida = os.path.join(ruta_carpeta_salida, "Limpieza")
            ruta_traduccion_salida = os.path.join(ruta_carpeta_salida, "Traduccion")

            # Inicializar las colas y el proceso para escribir JSON
            transcripcion_queue = mp.Queue()
            traduccion_queue = mp.Queue()
            transcripcion_process = JsonWriter(transcripcion_queue)
            traduccion_process = JsonWriter(traduccion_queue)
            transcripcion_process.start()
            traduccion_process.start()

            transcripcion_queue.put({
                'agregar_entrada' : {
                    'Título' : os.path.basename(ruta_carpeta_entrada),
                    'Páginas': cantidad_archivos,
                }
            })
            traduccion_queue.put({
                'agregar_entrada' : {
                    'Título' : os.path.basename(ruta_carpeta_entrada),
                    'Páginas': cantidad_archivos,
                }
            })
            
            processes = []
            for i in range(num_processes):
                # Seleccionar un lote de imágenes para cada proceso
                lote = lotes_imagenes[i]
                p = mp.Process(
                    target=process_func,
                    args=(
                        ruta_carpeta_entrada,
                        ruta_limpieza_salida,
                        ruta_traduccion_salida,
                        lote,
                        transcripcion_queue,
                        traduccion_queue,
                        logger,
                    ),
                    daemon=True)
                p.start()
                processes.append(p)
            
            for p in processes:
                p.join()
            for p in processes:
                p.terminate()
                
            transcripcion_queue.put({
                'ordenar_por_paginas' : {
                    'tipo' : 'Transcripción',
                }
            })
            traduccion_queue.put({
                'ordenar_por_paginas' : {
                    'tipo' : 'Traducción',
                }
            })
            # Señalizar que la escritura de JSON está completa
            transcripcion_queue.put({
                'guardar_en_archivo' : os.path.join(ruta_limpieza_salida, "Transcripción.json")
            })
            traduccion_queue.put({
                'guardar_en_archivo' : os.path.join(ruta_traduccion_salida, "Traducción.json")
            })

            # Esperar a que los procesos de escritura de JSON terminen
            transcripcion_process.join()
            traduccion_process.join()
            transcripcion_queue.close()
            traduccion_queue.close()
            return True
        except Exception as e:
            # Captura cualquier excepción y la imprime
            print(f"Error al procesar imágenes en paralelo: {e}")
            return False