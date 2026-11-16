"""Exercise the real running local service using a generated fixture; never calls external APIs."""
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
import httpx


def main():
    with tempfile.TemporaryDirectory(prefix='clipforge-acceptance-') as directory:
        root=Path(directory)
        video=root/'generated-test.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True,timeout=30)
        with httpx.Client(base_url='http://127.0.0.1:8000/api/v1',timeout=30) as client:
            assert client.get('/health').json()['status']=='healthy'
            search=client.post('/discovery/search',json={'query':'GTA VI acceptance','platforms':['youtube','reddit','twitch','tiktok','x','instagram'],'limit':1});search.raise_for_status()
            assert search.json()['result_count']==6
            with video.open('rb') as f:
                imported=client.post('/media/upload',files={'file':('Generated acceptance fixture.mp4',f,'video/mp4')},data={'authorization_status':'user_owned','authorization_notes':'Generated synthetic test pattern and tone, not user footage.'})
            imported.raise_for_status();media=imported.json()
            patched=client.patch('/media/'+media['id'],json={'subtitle_srt':'1\n00:00:00,000 --> 00:00:03,000\nGenerated acceptance test\n','publishing_metadata':{'title':'Generated acceptance fixture','description':'Synthetic test pattern and tone.','hashtags':'#test','hook':'Pipeline verification'}});patched.raise_for_status()
            queued=client.post('/processing/jobs',json={'media_id':media['id'],'profiles':['original','shorts_1080x1920'],'trim_start_seconds':.5,'trim_end_seconds':2.5,'normalize_audio':True});queued.raise_for_status();job=queued.json()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                state=client.get('/processing/jobs/'+job['id']).json()
                if state['status'] not in {'queued','running'}:break
                time.sleep(.5)
            assert state['status']=='completed',state
            outputs=client.get('/processing/jobs/'+job['id']+'/outputs').json()
            assert len(outputs)==2
            review=client.post('/media/'+media['id']+'/review',json={'action':'approved','notes':'Automated real-file acceptance validation'});review.raise_for_status()
            evidence=[]
            for output in outputs:
                result=client.get('/outputs/'+output['id']+'/download');result.raise_for_status()
                assert hashlib.sha256(result.content).hexdigest()==output['sha256']
                local=root/output['filename'];local.write_bytes(result.content)
                inspected=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_name,width,height:format=duration','-of','json',str(local)],capture_output=True,text=True,check=True)
                info=json.loads(inspected.stdout)
                if output['profile']=='shorts_1080x1920':assert (info['streams'][0]['width'],info['streams'][0]['height'])==(1080,1920)
                assert '00:00:00,000 --> 00:00:02,000' in client.get('/outputs/'+output['id']+'/subtitles').text
                evidence.append({'profile':output['profile'],'sha256':output['sha256'],'ffprobe':info})
            telegram_status=client.get('/system/status').json()['telegram']
            if telegram_status=='not_configured':
                telegram=client.post('/outputs/'+outputs[0]['id']+'/telegram-send',json={})
                assert telegram.status_code==409
            else:
                raise RuntimeError('Telegram is configured: live sending deliberately skipped. Run acceptance without Telegram credentials.')
            report={'media_id':media['id'],'job_id':job['id'],'status':state['status'],'outputs':evidence,'telegram':'setup_required','search_count':6}
            Path('docs/acceptance-result.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps(report,indent=2))


if __name__=='__main__':main()
