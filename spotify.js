
// Authorization token that must have been created previously. See : https://developer.spotify.com/documentation/web-api/concepts/authorization
const token = 'BQBCRL1TVF6KKfn6M2tD9k6dFaaIZlyxeQSTnLO21o-rhiKFUD1K6XQ2HS_ZjC32FP-58xG5zAHWGdvdaa5It0iswcEenqvmvgUsh1QwBgFpbW6nn4MCQiOwfArVwehn5IpB5dQAB0CCwRaf0BIdiMlxToUi-M6wMuN0MQ5JXlVKYTSUORv2rw4ADFzGxtc6MrEA2Pnwlya4AMDTHqseW3_4VfTOn-HCE3X51jIzDEt4Jlc31_9LG9YcKXFb4ER5FLBhYTtJ7R9Yft72J5VHfQoPt0dQ';
async function fetchWebApi(endpoint, method, body) {
  const res = await fetch(`https://api.spotify.com/${endpoint}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    method,
    body:JSON.stringify(body)
  });
  return await res.json();
}

async function getTopTracks(){
  // Endpoint reference : https://developer.spotify.com/documentation/web-api/reference/get-users-top-artists-and-tracks
  return (await fetchWebApi(
    'v1/me/top/tracks?time_range=long_term&limit=5', 'GET'
  )).items;
}

const topTracks = await getTopTracks();
console.log(
  topTracks?.map(
    ({name, artists}) =>
      `${name} by ${artists.map(artist => artist.name).join(', ')}`
  )
);



const playlistId = '42MJVcVmhDqMn90aNjhDsj';

<iframe
  title="Spotify Embed: Recommendation Playlist "
  src={`https://open.spotify.com/embed/playlist/42MJVcVmhDqMn90aNjhDsj?utm_source=generator&theme=0`}
  width="100%"
  height="100%"
  style={{ minHeight: '360px' }}
  frameBorder="0"
  allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
  loading="lazy"
/>