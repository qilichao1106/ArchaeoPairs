param([string]$DocxDir, [string]$OutFile)
# Extract readable text from word/document.xml, preserving paragraph/table structure.
$docPath = Join-Path $DocxDir 'word\document.xml'
$xml = New-Object System.Xml.XmlDocument
$xml.Load($docPath)
$ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$ns.AddNamespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')

$sb = New-Object System.Text.StringBuilder

function Get-Text([System.Xml.XmlNode]$node) {
    $t = ''
    foreach ($tn in $node.SelectNodes('.//w:t', $ns)) { $t += $tn.InnerText }
    return $t
}

function Get-CellText([System.Xml.XmlNode]$cell) {
    $parts = @()
    foreach ($p in $cell.SelectNodes('.//w:p', $ns)) {
        $parts += (Get-Text $p)
    }
    return ($parts -join ' / ')
}

$body = $xml.SelectSingleNode('//w:body', $ns)
foreach ($child in $body.ChildNodes) {
    if ($child.LocalName -eq 'p') {
        # detect style of paragraph (heading)
        $style = ''
        $pStyle = $child.SelectSingleNode('.//w:pStyle', $ns)
        if ($pStyle) { $style = $pStyle.GetAttribute('w:val', $ns.LookupNamespace('w')) }
        $txt = Get-Text $child
        $prefix = ''
        if ($style -match 'Heading' -or $style -match 'heading') { $prefix = "[H:$style] " }
        [void]$sb.AppendLine($prefix + $txt)
    }
    elseif ($child.LocalName -eq 'tbl') {
        [void]$sb.AppendLine('[TABLE]')
        foreach ($row in $child.SelectNodes('./w:tr', $ns)) {
            $cells = @()
            foreach ($cell in $row.SelectNodes('./w:tc', $ns)) {
                $cells += (Get-CellText $cell)
            }
            [void]$sb.AppendLine('| ' + ($cells -join ' | ') + ' |')
        }
        [void]$sb.AppendLine('[/TABLE]')
    }
}
[System.IO.File]::WriteAllText($OutFile, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))
Write-Output "Written: $OutFile ($((Get-Item $OutFile).Length) bytes)"
