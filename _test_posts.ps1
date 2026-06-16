$base = 'http://127.0.0.1:8500'
Write-Output "=== POSTS (3) ==="
$r = Invoke-WebRequest ($base + '/posts?username=silvva_bia&amount=3') -UseBasicParsing -TimeoutSec 90
$posts = ($r.Content | ConvertFrom-Json).posts
foreach ($p in $posts) {
    Write-Output ("post id=" + $p.id + " likes=" + $p.likes + " comments=" + $p.comments)
}
if ($posts.Count -gt 0) {
    $mid = $posts[0].id
    Write-Output ("`n=== LIKERS do post " + $mid + " ===")
    try {
        $rl = Invoke-WebRequest ($base + '/likers?media_id=' + $mid) -UseBasicParsing -TimeoutSec 90
        $ol = $rl.Content | ConvertFrom-Json
        Write-Output ("likers count: " + $ol.count)
    } catch { Write-Output ("ERRO likers: " + $_.Exception.Message) }

    Write-Output ("`n=== COMMENTS do post " + $mid + " ===")
    try {
        $rc = Invoke-WebRequest ($base + '/comments?media_id=' + $mid) -UseBasicParsing -TimeoutSec 90
        $oc = $rc.Content | ConvertFrom-Json
        Write-Output ("comments count: " + $oc.count)
    } catch { Write-Output ("ERRO comments: " + $_.Exception.Message) }
}
