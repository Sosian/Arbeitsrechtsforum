$CurrentDate = Get-Date
$TagString = "Sent_$($CurrentDate.Day).$($CurrentDate.Month).$($CurrentDate.Year)"
git tag -a $TagString -m $TagString


$NameOfNewFolder = "website_arbeitsrechtsforum_$($CurrentDate.Day)_$($CurrentDate.Month)_$($CurrentDate.Year)"
$PathToNewFolder = "..\$($NameOfNewFolder)"

New-Item -ItemType directory -Path $PathToNewFolder

Copy-Item .\* $PathToNewFolder -Recurse

Remove-Item $PathToNewFolder\publish.ps1
Remove-Item $PathToNewFolder\.git -Recurse -Force

$ArchivePath = "..\Versendete_Versionen\$($NameOfNewFolder).zip"
Compress-Archive -Path $PathToNewFolder -DestinationPath $ArchivePath

Remove-Item -Recurse -Force $PathToNewFolder