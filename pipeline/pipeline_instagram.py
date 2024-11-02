import tqdm
from generation_tools.image_generator.flux.flux import Flux

class PipelineInstagram:
    def __init__(self, post_content: dict):

        self.image_generator = Flux(load_on_demand=True)


   def generate_posts(self):
       for item in tqdm(self.post_content):
           _id, text, image_prompt = item["id"], item["text"], item["image"]
           image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")
           if not os.path.isfile(image_path):
               self.image_generator.generate_image(prompt=image_prompt, output_path=image_path, width=1080, height=1080,
                                                   retries=2)
               assert os.path.isfile(image_path), f"Image file {image_path} was not generated"