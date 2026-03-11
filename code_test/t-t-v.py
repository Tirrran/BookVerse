import fal_client

fal_client.api_key = "1ebfe714-1393-4021-b1d8-30b8fc758330:f6bb72aa4fb3959b06934054a32ae8c1"


prompt = """
A high-quality cinematic video opens with a wide shot of a bustling financial district in New York City during the 1950s—men in suits and hats rushing through the streets, newspapers filled with stock market updates. The camera zooms into a young Warren Buffett, a determined and focused man in his mid-twenties, walking with purpose towards an imposing financial institution. The sepia-toned setting emphasizes the era, while faint sounds of ticking stock market tickers and typewriters clatter in the background.

As Buffett enters a grand office, the scene transitions to his mentor, Benjamin Graham, explaining investment strategies on a large blackboard covered in financial charts and stock analysis. The camera captures Buffett’s intense concentration as he absorbs every word, his mind racing with ideas. A close-up shot of his hands flipping through Graham’s seminal book, The Intelligent Investor, reveals annotations and underlined key principles—highlighting Buffett's early dedication to value investing.

The scene shifts to a more intimate setting—Buffett sitting alone in a modest study, surrounded by stacks of investment reports, newspapers, and handwritten notes. A soft, golden light from a nearby lamp casts shadows on the walls, reflecting his tireless work ethic. The sound of a pen scratching against paper intensifies as he calculates potential investment returns with unwavering focus. His belief in disciplined investing is visually represented by a slow-motion montage of stock market fluctuations, followed by Buffett’s steady hand refusing to react impulsively.

Next, the video transports viewers to a dimly lit, elegant dining room at the Omaha Club in the late 1950s. Seven individuals—four relatives and three close friends—sit around a wooden table, engaged in quiet but serious discussion. Buffett, now slightly older and more confident, stands at the head of the table, handing out documents labeled Buffett Associates, Ltd.. He speaks passionately, gesturing as he presents the core principles of his investment philosophy. A slow zoom-in on his face captures the conviction in his eyes as he declares his vision for the future.

The video fast-forwards through time, seamlessly transitioning into color as we see a montage of Buffett’s transformation into a financial titan. Aerial shots of Omaha contrast with time-lapse footage of the stock market floor, newspapers with bold headlines announcing Berkshire Hathaway’s success, and Warren Buffett addressing eager investors at the annual shareholder meetings. His calm demeanor remains unchanged through market crashes and booms, reinforcing his steadfast belief in rational, long-term investing.

In a touching moment, the scene changes to Buffett signing documents for charitable donations, his hands aged but steady. He walks through a children’s hospital, shaking hands with doctors and smiling at young patients, showcasing his dedication to philanthropy. The camera lingers on a check with an astronomical sum, reinforcing his position as one of the world’s most generous philanthropists.

The video concludes with a powerful aerial shot of modern-day Omaha, the city lights glowing under a serene night sky. A voice-over of Buffett himself echoes in the background: "The best investment you can make is in yourself." The screen fades to black, leaving viewers inspired by the remarkable journey of one of history’s greatest investors."""
handler = fal_client.submit(
    "fal-ai/ltx-video",
    arguments={
        "prompt": prompt,
        "num_inference_steps": 45,
        "guidance_scale": 7,    
    },
    webhook_url="https://optional.webhook.url/for/results",


)

request_id = handler.request_id

import time

time.sleep(30)

result = fal_client.result("fal-ai/ltx-video", request_id)

print(result)